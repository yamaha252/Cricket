/* SPDX-License-Identifier: MIT */
#include "gatt.h"
#include "modes.h"
#include "pair.h"
#include "status.h"

#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(gatt, LOG_LEVEL_INF);

#define CRICKET_UUID(last) \
	BT_UUID_128_ENCODE(0x2083eb8d, 0x7651, 0x438b, 0xb7fb, 0x75aff5da9c00 | (last))

static const struct bt_uuid_128 svc_uuid = BT_UUID_INIT_128(CRICKET_UUID(0x00));
static const struct bt_uuid_128 status_uuid = BT_UUID_INIT_128(CRICKET_UUID(0x01));
static const struct bt_uuid_128 control_uuid = BT_UUID_INIT_128(CRICKET_UUID(0x02));

#define STATUS_OFFSET offsetof(struct cricket_payload, version) /* skip Company ID */

static bool notify_enabled;

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
	default:
		LOG_WRN("unknown command 0x%02x", cmd[0]);
		return BT_GATT_ERR(BT_ATT_ERR_NOT_SUPPORTED);
	}
	return len;
}

BT_GATT_SERVICE_DEFINE(cricket_svc,
	BT_GATT_PRIMARY_SERVICE(&svc_uuid),
	BT_GATT_CHARACTERISTIC(&status_uuid.uuid, BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_READ, read_status, NULL, NULL),
	BT_GATT_CCC(status_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	/* Commands only from a bonded phone: the link must be encrypted (pair.c) */
	BT_GATT_CHARACTERISTIC(&control_uuid.uuid, BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_WRITE_ENCRYPT, NULL, write_control, NULL),
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
