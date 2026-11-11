/* SPDX-License-Identifier: MIT */
#include "adv.h"
#include "config.h"

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/hci.h>
#include <zephyr/bluetooth/hci_vs.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/byteorder.h>
#include <string.h>

LOG_MODULE_REGISTER(adv, LOG_LEVEL_INF);

enum { SET_CODED = CFG_SET_CODED, SET_1M = CFG_SET_1M, SET_COUNT = CFG_SET_COUNT };

struct adv_set {
	const char *name;
	struct bt_le_ext_adv *adv;
	uint32_t options;
	uint16_t interval_ms; /* 0: set is off */
};

static struct adv_set sets[SET_COUNT] = {
	[SET_CODED] = {
		.name = "coded",
		.options = BT_LE_ADV_OPT_CONN | BT_LE_ADV_OPT_EXT_ADV | BT_LE_ADV_OPT_CODED |
			   BT_LE_ADV_OPT_REQUIRE_S8_CODING,
	},
	[SET_1M] = {
		.name = "1m",
		.options = BT_LE_ADV_OPT_CONN, /* legacy ADV_IND, scannable */
	},
};

static struct cricket_payload payload;
static const uint8_t ad_flags = BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR;

static struct bt_data ad[] = {
	BT_DATA(BT_DATA_FLAGS, &ad_flags, sizeof(ad_flags)),
	BT_DATA(BT_DATA_MANUFACTURER_DATA, &payload, sizeof(payload)),
};

static struct bt_data sd[1]; /* device name, set from the app (config.c) */

static enum cricket_mode cur_mode = MODE_STANDBY;
static bool cur_quiet;

#define ADV_INTERVAL_MAX 0x4000 /* 10.24 s in 0.625 ms units; the host refuses more */

/* Interval for the set in the mode, ms; 0: off. Intervals per mode come from config.c. */
static uint16_t interval_for(const struct cricket_cfg *c, int set, enum cricket_mode mode,
			     bool quiet)
{
	if (mode >= CFG_MODES || (mode == MODE_ON_DRONE && quiet)) {
		return 0;
	}
	return c->interval_ms[mode][set];
}

static struct bt_le_adv_param param_for(const struct adv_set *s, uint16_t ms)
{
	/* 0.625 ms units; the +10 % window must not pass the limit (10 s intervals) */
	uint32_t min = MIN(ms * 8U / 5U, ADV_INTERVAL_MAX);
	uint32_t max = MIN(min + min / 10, ADV_INTERVAL_MAX);
	struct bt_le_adv_param p = BT_LE_ADV_PARAM_INIT(s->options, min, max, NULL);

	p.sid = s - sets;
	return p;
}

static void set_tx_power(struct adv_set *s, int8_t dbm)
{
	struct bt_hci_cp_vs_write_tx_power_level *cp;
	struct bt_hci_rp_vs_write_tx_power_level *rp;
	struct net_buf *buf, *rsp = NULL;
	uint8_t handle;
	int err;

	err = bt_hci_get_adv_handle(s->adv, &handle);
	if (err) {
		LOG_WRN("%s: no handle (%d)", s->name, err);
		return;
	}

	buf = bt_hci_cmd_alloc(K_FOREVER);
	if (!buf) {
		return;
	}
	cp = net_buf_add(buf, sizeof(*cp));
	cp->handle_type = BT_HCI_VS_LL_HANDLE_TYPE_ADV;
	cp->handle = sys_cpu_to_le16(handle);
	cp->tx_power_level = dbm;

	err = bt_hci_cmd_send_sync(BT_HCI_OP_VS_WRITE_TX_POWER_LEVEL, buf, &rsp);
	if (err) {
		LOG_WRN("%s: TX power not set (%d)", s->name, err);
		return;
	}
	rp = (void *)rsp->data;
	LOG_DBG("%s: TX power %d dBm", s->name, rp->selected_tx_power);
	net_buf_unref(rsp);
}

static void set_data(struct adv_set *s)
{
	int err;

	if (s == &sets[SET_1M]) {
		const char *name = bt_get_name();

		sd[0] = (struct bt_data)BT_DATA(BT_DATA_NAME_COMPLETE, name, strlen(name));
		err = bt_le_ext_adv_set_data(s->adv, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
	} else {
		err = bt_le_ext_adv_set_data(s->adv, ad, ARRAY_SIZE(ad), NULL, 0);
	}
	if (err) {
		LOG_WRN("%s: set data failed (%d)", s->name, err);
	}
}

static void start(struct adv_set *s)
{
	int err;

	if (!s->interval_ms) {
		return;
	}
	err = bt_le_ext_adv_start(s->adv, BT_LE_EXT_ADV_START_DEFAULT);
	/* -ENOMEM: every connection is in use, recycled() starts the set later */
	if (err && err != -EALREADY && err != -ENOMEM) {
		LOG_WRN("%s: start failed (%d)", s->name, err);
	}
}

/*
 * A connection stops the set it came through. Restart it at once while another
 * connection is free, so that a connected phone does not hide the beacon from
 * other phones, and again once a connection object is released. On the system
 * work queue, like every other change of the sets.
 */
static void restart_fn(struct k_work *w)
{
	for (int i = 0; i < SET_COUNT; i++) {
		start(&sets[i]);
	}
}

static K_WORK_DEFINE(restart_work, restart_fn);

static void connected(struct bt_conn *conn, uint8_t err)
{
	k_work_submit(&restart_work);
}

static void recycled(void)
{
	k_work_submit(&restart_work);
}

BT_CONN_CB_DEFINE(adv_conn_cb) = {
	.connected = connected,
	.recycled = recycled,
};

int adv_init(void)
{
	int err;

	status_build(&payload);

	for (int i = 0; i < SET_COUNT; i++) {
		struct adv_set *s = &sets[i];
		struct bt_le_adv_param p = param_for(s, 1000);

		err = bt_le_ext_adv_create(&p, NULL, &s->adv);
		if (err) {
			LOG_ERR("%s: create failed (%d)", s->name, err);
			return err;
		}
		set_data(s); /* TX power is set by adv_apply() before the first start */
	}
	return 0;
}

static void disconnect(struct bt_conn *conn, void *data)
{
	int err = bt_conn_disconnect(conn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);

	if (err && err != -ENOTCONN) {
		LOG_WRN("disconnect failed (%d)", err);
	}
}

void adv_apply(enum cricket_mode mode, bool quiet)
{
	struct cricket_cfg c;

	config_get(&c);
	cur_mode = mode;
	cur_quiet = quiet;

	/*
	 * Flying: stopping advertising is not enough, a phone left connected on
	 * the bench would keep the link up next to the ELRS receiver.
	 */
	if (mode == MODE_ON_DRONE && quiet) {
		bt_conn_foreach(BT_CONN_TYPE_LE, disconnect, NULL);
	}

	for (int i = 0; i < SET_COUNT; i++) {
		struct adv_set *s = &sets[i];
		uint16_t ms = interval_for(&c, i, mode, quiet);
		struct bt_le_adv_param p;
		int err;

		if (ms == s->interval_ms) {
			continue;
		}
		bt_le_ext_adv_stop(s->adv);
		s->interval_ms = ms;
		if (!ms) {
			LOG_INF("%s: off", s->name);
			continue;
		}
		p = param_for(s, ms);
		err = bt_le_ext_adv_update_param(s->adv, &p);
		if (err) {
			LOG_WRN("%s: update param failed (%d)", s->name, err);
		}
		/* after the parameters, which carry "no preference" for the power */
		set_tx_power(s, c.tx_dbm[i]);
		start(s);
		LOG_INF("%s: every %u ms", s->name, ms);
	}
}

void adv_refresh(void)
{
	status_build(&payload);
	for (int i = 0; i < SET_COUNT; i++) {
		set_data(&sets[i]);
	}
}

void adv_reload(void)
{
	if (cur_mode == MODE_SHIP) {
		return;
	}
	status_build(&payload);
	for (int i = 0; i < SET_COUNT; i++) {
		struct adv_set *s = &sets[i];

		bt_le_ext_adv_stop(s->adv);
		s->interval_ms = UINT16_MAX; /* forces adv_apply to set it up again */
		set_data(s);
	}
	adv_apply(cur_mode, cur_quiet);
}

void adv_stop_all(void)
{
	for (int i = 0; i < SET_COUNT; i++) {
		bt_le_ext_adv_stop(sets[i].adv);
		sets[i].interval_ms = 0;
	}
	cur_mode = MODE_SHIP;
}
