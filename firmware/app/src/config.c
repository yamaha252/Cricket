/* SPDX-License-Identifier: MIT */
#include "config.h"
#include "adv.h"

#include <string.h>
#include <zephyr/bluetooth/att.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/settings/settings.h>
#include <zephyr/sys/byteorder.h>

LOG_MODULE_REGISTER(config, LOG_LEVEL_INF);

#define CFG_STORE_VER 2

BUILD_ASSERT(CFG_NAME_MAX <= CONFIG_BT_DEVICE_NAME_MAX);
BUILD_ASSERT(sizeof(CONFIG_BT_DEVICE_NAME) - 1 <= CFG_NAME_MAX);

/* Defaults, docs/protocol.md «Наборы рекламы»: {coded, 1M} */
static const struct cricket_cfg defaults = {
	.tx_dbm = {8, 8},
	.rssi_1m = CONFIG_CRICKET_RSSI_1M,
	.interval_ms = {
		[MODE_ON_DRONE] = {1000, 1000},
		[MODE_ESCALATE] = {1000, 2000},
		[MODE_ALARM] = {1000, 2000},
		[MODE_BEACON] = {2000, 4000},
		[MODE_STANDBY] = {5000, 5000},
		[MODE_LOW_BAT] = {10000, 10000},
	},
	.preflight = 1,
};

struct cfg_store {
	uint8_t ver;
	struct cricket_cfg cfg;
};

static struct k_spinlock lock;
static struct cricket_cfg cfg = defaults;
static char new_name[CFG_NAME_MAX + 1];
static bool name_changed;
static char owner[CFG_OWNER_MAX];
static uint8_t owner_len;
static bool owner_changed;

static void apply_fn(struct k_work *w);
static K_WORK_DEFINE(apply_work, apply_fn);

static bool valid(const struct cricket_cfg *c)
{
	for (int s = 0; s < CFG_SET_COUNT; s++) {
		if (c->tx_dbm[s] < CFG_TX_MIN_DBM || c->tx_dbm[s] > CFG_TX_MAX_DBM) {
			return false;
		}
	}
	if (c->rssi_1m > 0 || c->preflight > 1) {
		return false;
	}
	for (int m = 0; m < CFG_MODES; m++) {
		bool any = false;

		for (int s = 0; s < CFG_SET_COUNT; s++) {
			uint16_t ms = c->interval_ms[m][s];

			if (ms && (ms < CFG_INTERVAL_MIN_MS || ms > CFG_INTERVAL_MAX_MS)) {
				return false;
			}
			any |= ms != 0;
		}
		/* A mode with both sets off could not be reached to undo it */
		if (!any) {
			return false;
		}
	}
	return true;
}

static int cfg_set(const char *key, size_t len, settings_read_cb read_cb, void *cb_arg)
{
	struct cfg_store st;

	if (!strcmp(key, "owner")) {
		ssize_t n = len <= CFG_OWNER_MAX ? read_cb(cb_arg, owner, len) : -EINVAL;

		owner_len = n > 0 ? n : 0;
		return 0;
	}
	if (strcmp(key, "cfg")) {
		return -ENOENT;
	}
	if (len != sizeof(st) || read_cb(cb_arg, &st, sizeof(st)) != sizeof(st) ||
	    st.ver != CFG_STORE_VER || !valid(&st.cfg)) {
		LOG_WRN("stored settings ignored, using defaults");
		return 0;
	}
	K_SPINLOCK(&lock) {
		cfg = st.cfg;
	}
	return 0;
}

SETTINGS_STATIC_HANDLER_DEFINE(cricket, "cricket", NULL, cfg_set, NULL, NULL);

void config_get(struct cricket_cfg *out)
{
	K_SPINLOCK(&lock) {
		*out = cfg;
	}
}

bool config_preflight(void)
{
	bool v;

	K_SPINLOCK(&lock) {
		v = cfg.preflight;
	}
	return v;
}

size_t config_owner(char *buf, size_t size)
{
	size_t n;

	K_SPINLOCK(&lock) {
		n = MIN(owner_len, size);
		memcpy(buf, owner, n);
	}
	return n;
}

int8_t config_rssi_1m(void)
{
	int8_t v;

	K_SPINLOCK(&lock) {
		v = cfg.rssi_1m;
	}
	return v;
}

static void apply_fn(struct k_work *w)
{
	struct cfg_store st = {.ver = CFG_STORE_VER};
	char name[CFG_NAME_MAX + 1] = "";
	char own[CFG_OWNER_MAX];
	int own_len = -1; /* unchanged */
	int err;

	K_SPINLOCK(&lock) {
		st.cfg = cfg;
		if (name_changed) {
			strcpy(name, new_name);
			name_changed = false;
		}
		if (owner_changed) {
			memcpy(own, owner, owner_len);
			own_len = owner_len;
			owner_changed = false;
		}
	}
	if (own_len > 0) {
		err = settings_save_one("cricket/owner", own, own_len);
	} else if (own_len == 0) {
		err = settings_delete("cricket/owner");
	} else {
		err = 0;
	}
	if (err) {
		LOG_WRN("owner contact not saved (%d)", err);
	}
	if (name[0]) {
		err = bt_set_name(name); /* the host stores it in settings itself */
		if (err) {
			LOG_WRN("name not set (%d)", err);
		}
	}
	err = settings_save_one("cricket/cfg", &st, sizeof(st));
	if (err) {
		LOG_WRN("settings not saved (%d)", err);
	}
	adv_reload();
	LOG_INF("settings applied");
}

static size_t put(uint8_t *buf, size_t size, size_t at, uint8_t key, const void *v, uint8_t len)
{
	if (at + 2 + len > size) {
		return at;
	}
	buf[at] = key;
	buf[at + 1] = len;
	memcpy(&buf[at + 2], v, len);
	return at + 2 + len;
}

size_t config_encode(uint8_t *buf, size_t size)
{
	struct cricket_cfg c;
	const char *name = bt_get_name();
	size_t n = 0;

	config_get(&c);
	n = put(buf, size, n, CFG_KEY_NAME, name, MIN(strlen(name), CFG_NAME_MAX));
	n = put(buf, size, n, CFG_KEY_TX_CODED, &c.tx_dbm[CFG_SET_CODED], 1);
	n = put(buf, size, n, CFG_KEY_TX_1M, &c.tx_dbm[CFG_SET_1M], 1);
	n = put(buf, size, n, CFG_KEY_RSSI_1M, &c.rssi_1m, 1);
	n = put(buf, size, n, CFG_KEY_PREFLIGHT, &c.preflight, 1);
	{
		char own[CFG_OWNER_MAX];
		size_t len = config_owner(own, sizeof(own));

		n = put(buf, size, n, CFG_KEY_OWNER, own, len);
	}
	for (int m = 0; m < CFG_MODES; m++) {
		uint8_t v[4];

		sys_put_le16(c.interval_ms[m][CFG_SET_CODED], &v[0]);
		sys_put_le16(c.interval_ms[m][CFG_SET_1M], &v[2]);
		n = put(buf, size, n, CFG_KEY_INTERVALS + m, v, sizeof(v));
	}
	return n;
}

uint8_t config_write(const uint8_t *buf, size_t len)
{
	struct cricket_cfg c;
	char name[CFG_NAME_MAX + 1] = "";
	char own[CFG_OWNER_MAX];
	int own_len = -1; /* not in this write */
	size_t at = 0;

	config_get(&c);
	while (at < len) {
		uint8_t key, vlen;
		const uint8_t *v;

		if (len - at < 2 || len - at - 2 < buf[at + 1]) {
			return BT_ATT_ERR_INVALID_ATTRIBUTE_LEN;
		}
		key = buf[at];
		vlen = buf[at + 1];
		v = &buf[at + 2];
		at += 2 + vlen;

		switch (key) {
		case CFG_KEY_NAME:
			if (vlen < 1 || vlen > CFG_NAME_MAX || memchr(v, '\0', vlen)) {
				return BT_ATT_ERR_OUT_OF_RANGE;
			}
			memcpy(name, v, vlen);
			name[vlen] = '\0';
			break;
		case CFG_KEY_OWNER:
			if (vlen > CFG_OWNER_MAX || memchr(v, '\0', vlen)) {
				return BT_ATT_ERR_OUT_OF_RANGE;
			}
			memcpy(own, v, vlen);
			own_len = vlen;
			break;
		case CFG_KEY_TX_CODED:
		case CFG_KEY_TX_1M:
		case CFG_KEY_RSSI_1M:
		case CFG_KEY_PREFLIGHT:
			if (vlen != 1) {
				return BT_ATT_ERR_INVALID_ATTRIBUTE_LEN;
			}
			if (key == CFG_KEY_RSSI_1M) {
				c.rssi_1m = (int8_t)v[0];
			} else if (key == CFG_KEY_PREFLIGHT) {
				c.preflight = v[0];
			} else {
				c.tx_dbm[key == CFG_KEY_TX_CODED ? CFG_SET_CODED : CFG_SET_1M] =
					(int8_t)v[0];
			}
			break;
		default:
			if (key < CFG_KEY_INTERVALS || key >= CFG_KEY_INTERVALS + CFG_MODES) {
				return BT_ATT_ERR_NOT_SUPPORTED;
			}
			if (vlen != 4) {
				return BT_ATT_ERR_INVALID_ATTRIBUTE_LEN;
			}
			c.interval_ms[key - CFG_KEY_INTERVALS][CFG_SET_CODED] = sys_get_le16(&v[0]);
			c.interval_ms[key - CFG_KEY_INTERVALS][CFG_SET_1M] = sys_get_le16(&v[2]);
			break;
		}
	}
	if (!valid(&c)) {
		return BT_ATT_ERR_OUT_OF_RANGE;
	}

	K_SPINLOCK(&lock) {
		cfg = c;
		if (name[0]) {
			strcpy(new_name, name);
			name_changed = true;
		}
		if (own_len >= 0) {
			memcpy(owner, own, own_len);
			owner_len = own_len;
			owner_changed = true;
		}
	}
	k_work_submit(&apply_work);
	return 0;
}

void config_reset(void)
{
	K_SPINLOCK(&lock) {
		cfg = defaults;
		strcpy(new_name, CONFIG_BT_DEVICE_NAME);
		name_changed = true;
	}
	k_work_submit(&apply_work);
}
