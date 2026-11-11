/* SPDX-License-Identifier: MIT */
#include "status.h"
#include "config.h"

#include <zephyr/kernel.h>
#include <zephyr/drivers/hwinfo.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/crc.h>

static struct k_spinlock lock;
static uint32_t id;
static enum cricket_mode mode = MODE_STANDBY;
static int64_t mode_since_ms;
static uint8_t flags;
static uint16_t battery_mv;
static int32_t lat_e7, lon_e7;

void status_init(void)
{
	uint8_t dev[16];
	ssize_t n = hwinfo_get_device_id(dev, sizeof(dev));

	id = n > 0 ? crc32_ieee(dev, n) : 0;
	mode_since_ms = k_uptime_get();
}

uint32_t status_id(void)
{
	return id;
}

enum cricket_mode status_mode(void)
{
	return mode;
}

void status_set_mode(enum cricket_mode m)
{
	K_SPINLOCK(&lock) {
		mode = m;
		mode_since_ms = k_uptime_get();
	}
}

void status_update_flags(uint8_t set, uint8_t clear)
{
	K_SPINLOCK(&lock) {
		flags = (flags & ~clear) | set;
	}
}

void status_set_battery(uint16_t mv)
{
	K_SPINLOCK(&lock) {
		battery_mv = mv;
	}
}

void status_set_position(int32_t lat, int32_t lon)
{
	K_SPINLOCK(&lock) {
		lat_e7 = lat;
		lon_e7 = lon;
		flags |= FLAG_POS_VALID;
	}
}

void status_build(struct cricket_payload *out)
{
	int8_t rssi_1m = config_rssi_1m();

	K_SPINLOCK(&lock) {
		int64_t minutes = (k_uptime_get() - mode_since_ms) / 60000;

		out->company = sys_cpu_to_le16(CRICKET_COMPANY_ID);
		out->version = CRICKET_PROTO_VER;
		out->id = sys_cpu_to_le32(id);
		out->mode = mode;
		out->flags = flags;
		out->battery_mv = sys_cpu_to_le16(battery_mv);
		out->rssi_1m = rssi_1m;
		out->mode_minutes = sys_cpu_to_le16(MIN(minutes, UINT16_MAX));
		out->lat_e7 = sys_cpu_to_le32(lat_e7);
		out->lon_e7 = sys_cpu_to_le32(lon_e7);
	}
}

const char *status_mode_name(enum cricket_mode m)
{
	static const char *const names[] = {
		"ON_DRONE", "ESCALATE", "ALARM", "BEACON", "STANDBY", "LOW_BAT", "SHIP",
	};

	return m < ARRAY_SIZE(names) ? names[m] : "?";
}
