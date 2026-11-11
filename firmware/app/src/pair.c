/* SPDX-License-Identifier: MIT */
#include "pair.h"
#include "modes.h"
#include "status.h"

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(pair, LOG_LEVEL_INF);

#define PAIR_WINDOW_S 60

static atomic_t open;
static bt_addr_le_t keep_addr;

static void close_fn(struct k_work *w);
static void forget_fn(struct k_work *w);
static K_WORK_DELAYABLE_DEFINE(close_work, close_fn);
static K_WORK_DEFINE(forget_work, forget_fn);

static void close_fn(struct k_work *w)
{
	if (atomic_clear(&open)) {
		status_update_flags(0, FLAG_PAIRING);
		LOG_INF("pairing window closed");
	}
}

static enum bt_security_err pairing_accept(struct bt_conn *conn,
					   const struct bt_conn_pairing_feat *const feat)
{
	if (!atomic_get(&open)) {
		LOG_INF("pairing refused: window closed");
		return BT_SECURITY_ERR_PAIR_NOT_ALLOWED;
	}
	return BT_SECURITY_ERR_SUCCESS;
}

static struct bt_conn_auth_cb auth_cb = {
	.pairing_accept = pairing_accept,
};

static void pairing_complete(struct bt_conn *conn, bool bonded)
{
	char addr[BT_ADDR_LE_STR_LEN];

	bt_addr_le_to_str(bt_conn_get_dst(conn), addr, sizeof(addr));
	LOG_INF("paired with %s, bonded %d", addr, bonded);
	if (bonded) {
		k_work_reschedule(&close_work, K_NO_WAIT);
		modes_post(EV_PAIRED, 0);
	}
}

static void pairing_failed(struct bt_conn *conn, enum bt_security_err reason)
{
	LOG_INF("pairing failed (%d)", reason);
}

static struct bt_conn_auth_info_cb auth_info_cb = {
	.pairing_complete = pairing_complete,
	.pairing_failed = pairing_failed,
};

static void forget_one(const struct bt_bond_info *info, void *user_data)
{
	if (!bt_addr_le_eq(&info->addr, &keep_addr)) {
		char addr[BT_ADDR_LE_STR_LEN];

		bt_addr_le_to_str(&info->addr, addr, sizeof(addr));
		LOG_INF("forgetting %s", addr);
		bt_unpair(BT_ID_DEFAULT, &info->addr);
	}
}

static void forget_fn(struct k_work *w)
{
	bt_foreach_bond(BT_ID_DEFAULT, forget_one, NULL);
}

static void count_bond(const struct bt_bond_info *info, void *user_data)
{
	(*(int *)user_data)++;
}

int pair_init(void)
{
	int bonds = 0;
	int err = bt_conn_auth_cb_register(&auth_cb);

	err = err ?: bt_conn_auth_info_cb_register(&auth_info_cb);
	if (err) {
		LOG_ERR("auth callbacks failed (%d)", err);
		return err;
	}
	bt_foreach_bond(BT_ID_DEFAULT, count_bond, &bonds);
	LOG_INF("%d bonded phone(s)", bonds);
	return 0;
}

void pair_open(void)
{
	atomic_set(&open, 1);
	status_update_flags(FLAG_PAIRING, 0);
	k_work_reschedule(&close_work, K_SECONDS(PAIR_WINDOW_S));
	LOG_INF("pairing window open for %d s", PAIR_WINDOW_S);
}

void pair_forget_others(const bt_addr_le_t *keep)
{
	bt_addr_le_copy(&keep_addr, keep);
	k_work_submit(&forget_work);
}
