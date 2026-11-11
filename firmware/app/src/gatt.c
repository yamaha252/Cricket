/* SPDX-License-Identifier: MIT */
#include "gatt.h"
#include "config.h"
#include "modes.h"
#include "pair.h"
#include "status.h"

#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(gatt, LOG_LEVEL_INF);

#define CRICKET_UUID(last) \
	BT_UUID_128_ENCODE(0x2083eb8d, 0x7651, 0x438b, 0xb7fb, 0x75aff5da9c00 | (last))

static const struct bt_uuid_128 svc_uuid = BT_UUID_INIT_128(CRICKET_UUID(0x00));
static const struct bt_uuid_128 status_uuid = BT_UUID_INIT_128(CRICKET_UUID(0x01));
static const struct bt_uuid_128 control_uuid = BT_UUID_INIT_128(CRICKET_UUID(0x02));
static const struct bt_uuid_128 settings_uuid = BT_UUID_INIT_128(CRICKET_UUID(0x03));

#define STATUS_OFFSET offsetof(struct cricket_payload, version) /* skip Company ID */

#define OPEN_FIND_MAX_S 60 /* FIND from an unbonded phone during an alarm */

static bool notify_enabled;

static bool alarming(void)
{
	enum cricket_mode m = status_mode();

	return m == MODE_ESCALATE || m == MODE_ALARM || m == MODE_BEACON;
}

static ssize_t read_status(struct bt_conn *conn, const struct bt_gatt_attr *attr, void *buf,
			   uint16_t len, uint16_t offset)
{
	struct cricket_payload p;

	status_build(&p);
	return bt_gatt_attr_read(conn, attr, buf, len, offset, (uint8_t *)&p + STATUS_OFFSET,
				 sizeof(p) - STATUS_OFFSET);
}

static void status_ccc_changed(const struct bt_gatt_attr *attr, uint16_t value)
{
	notify_enabled = value == BT_GATT_CCC_NOTIFY;
}

static ssize_t write_control(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			     const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
	const uint8_t *cmd = buf;

	if (offset) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
	}
	if (len < 1) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
	}

	/*
	 * Commands need a bonded (encrypted) link, except FIND while the beacon is
	 * in ESCALATE, ALARM or BEACON: a helper's phone may make a crashed drone
	 * beep. The error makes Android offer pairing, which pair.c accepts only
	 * inside the pairing window.
	 */
	if (bt_conn_get_security(conn) < BT_SECURITY_L2) {
		if (cmd[0] != CRICKET_CMD_FIND || len != 2 || !alarming()) {
			return BT_GATT_ERR(BT_ATT_ERR_INSUFFICIENT_ENCRYPTION);
		}
		modes_post(EV_CMD_FIND, MIN(cmd[1], OPEN_FIND_MAX_S));
		return len;
	}

	switch (cmd[0]) {
	case CRICKET_CMD_FIND:
		if (len != 2) {
			return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
		}
		modes_post(EV_CMD_FIND, cmd[1]);
		break;
	case CRICKET_CMD_SILENCE:
		modes_post(EV_CMD_SILENCE, 0);
		break;
	case CRICKET_CMD_DFU:
		modes_post(EV_DFU, 0);
		break;
	case CRICKET_CMD_FORGET:
		pair_forget_others(bt_conn_get_dst(conn));
		break;
	case CRICKET_CMD_DEFAULTS:
		config_reset();
		break;
	default:
		LOG_WRN("unknown command 0x%02x", cmd[0]);
		return BT_GATT_ERR(BT_ATT_ERR_NOT_SUPPORTED);
	}
	return len;
}

static ssize_t read_settings(struct bt_conn *conn, const struct bt_gatt_attr *attr, void *buf,
			     uint16_t len, uint16_t offset)
{
	uint8_t v[96];
	size_t n = config_encode(v, sizeof(v));

	return bt_gatt_attr_read(conn, attr, buf, len, offset, v, n);
}

static ssize_t write_settings(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			      const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
	uint8_t err;

	if (offset) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
	}
	err = config_write(buf, len);
	if (err) {
		LOG_WRN("settings rejected (0x%02x)", err);
		return BT_GATT_ERR(err);
	}
	return len;
}

BT_GATT_SERVICE_DEFINE(cricket_svc,
	BT_GATT_PRIMARY_SERVICE(&svc_uuid),
	BT_GATT_CHARACTERISTIC(&status_uuid.uuid, BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_READ, read_status, NULL, NULL),
	BT_GATT_CCC(status_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	/* Encryption is checked per command in write_control */
	BT_GATT_CHARACTERISTIC(&control_uuid.uuid, BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_WRITE, NULL, write_control, NULL),
	/* Bluetooth settings (config.c): only over a bonded link */
	BT_GATT_CHARACTERISTIC(&settings_uuid.uuid, BT_GATT_CHRC_READ | BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_READ_ENCRYPT | BT_GATT_PERM_WRITE_ENCRYPT,
			       read_settings, write_settings, NULL),
);

void gatt_notify_status(void)
{
	struct cricket_payload p;

	if (!notify_enabled) {
		return;
	}
	status_build(&p);
	bt_gatt_notify(NULL, &cricket_svc.attrs[2], (uint8_t *)&p + STATUS_OFFSET,
		       sizeof(p) - STATUS_OFFSET);
}
