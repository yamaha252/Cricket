/* SPDX-License-Identifier: MIT */
/*
 * Bluetooth settings changed from the app: device name, TX power and
 * advertising intervals per set and mode, calibrated RSSI at 1 m, preflight
 * beep, owner contact. Stored in the settings partition; docs/protocol.md
 * «Настройки».
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <zephyr/sys/util.h>

#include "status.h"

enum { CFG_SET_CODED, CFG_SET_1M, CFG_SET_COUNT };

/* Modes whose intervals are configurable: ON_DRONE (disarmed) .. LOW_BAT */
#define CFG_MODES (MODE_LOW_BAT + 1)

struct cricket_cfg {
	int8_t tx_dbm[CFG_SET_COUNT];
	int8_t rssi_1m;
	uint16_t interval_ms[CFG_MODES][CFG_SET_COUNT]; /* 0: set off in that mode */
	uint8_t preflight; /* 1: beep the preflight check when 5 V comes */
};

/* Setting keys in the TLV encoding of the settings characteristic */
#define CFG_KEY_NAME        0x01
#define CFG_KEY_TX_CODED    0x02
#define CFG_KEY_TX_1M       0x03
#define CFG_KEY_RSSI_1M     0x04
#define CFG_KEY_OWNER       0x05 /* contact shown to whoever finds the drone */
#define CFG_KEY_PREFLIGHT   0x06
#define CFG_KEY_INTERVALS   0x10 /* + mode, value: uint16 coded ms, uint16 1M ms */

#define CFG_NAME_MAX        20
#define CFG_OWNER_MAX       64
#define CFG_TX_MIN_DBM      (-40)
#define CFG_TX_MAX_DBM      8
#define CFG_INTERVAL_MIN_MS 100
#define CFG_INTERVAL_MAX_MS 10240 /* legacy advertising limit */

void config_get(struct cricket_cfg *out);
int8_t config_rssi_1m(void);
bool config_preflight(void);
/* Owner contact, UTF-8 without a terminating zero; returns its length (0: none). */
size_t config_owner(char *buf, size_t size);

/* Encode all settings as TLV {key, len, value}; returns the length. */
size_t config_encode(uint8_t *buf, size_t size);
/*
 * Validate a TLV list from the app and apply it as a whole; nothing changes if
 * any entry is bad. Returns 0 or a BT_ATT_ERR_* code. Saving and restarting
 * advertising happen on the system work queue.
 */
uint8_t config_write(const uint8_t *buf, size_t len);
/* Back to defaults (name, power, intervals, RSSI, preflight); bonds and the owner contact are kept. */
void config_reset(void);
