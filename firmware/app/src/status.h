/* SPDX-License-Identifier: MIT */
/* Beacon state shared by the advertising sets and the GATT service (docs/protocol.md). */
#pragma once

#include <stdint.h>
#include <zephyr/sys/util.h>
#include <zephyr/toolchain.h>

#define CRICKET_COMPANY_ID  0xFFFF /* Bluetooth SIG value reserved for tests */
#define CRICKET_PROTO_VER   0x01

enum cricket_mode {
	MODE_ON_DRONE = 0,
	MODE_ESCALATE = 1,
	MODE_ALARM = 2,
	MODE_BEACON = 3,
	MODE_STANDBY = 4,
	MODE_LOW_BAT = 5,
	MODE_SHIP = 6,
};

#define FLAG_VIN       BIT(0) /* 5 V from the flight controller present */
#define FLAG_CHARGING  BIT(1)
#define FLAG_POS_VALID BIT(2) /* latitude/longitude hold a GPS fix */
#define FLAG_BUZZING   BIT(3)
#define FLAG_WAS_ARMED BIT(4) /* armed when 5 V was lost */
#define FLAG_IMPACT    BIT(5) /* impact shortly before 5 V was lost */

struct cricket_payload {
	uint16_t company;
	uint8_t version;
	uint32_t id;
	uint8_t mode;
	uint8_t flags;
	uint16_t battery_mv;
	int8_t rssi_1m;
	uint16_t mode_minutes;
	int32_t lat_e7;
	int32_t lon_e7;
} __packed;

BUILD_ASSERT(sizeof(struct cricket_payload) == 22, "payload must fit legacy advertising");

void status_init(void);
uint32_t status_id(void);
enum cricket_mode status_mode(void);
void status_set_mode(enum cricket_mode mode);
void status_update_flags(uint8_t set, uint8_t clear);
void status_set_battery(uint16_t mv);
void status_set_position(int32_t lat_e7, int32_t lon_e7);
void status_build(struct cricket_payload *out);
const char *status_mode_name(enum cricket_mode mode);
