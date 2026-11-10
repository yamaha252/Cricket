/* SPDX-License-Identifier: MIT */
/* Operating modes, concept.md «Режимы работы». */
#pragma once

#include <stdint.h>

enum mode_event {
	EV_BTN_SHORT,
	EV_BTN_HOLD3,
	EV_BTN_HOLD8,
	EV_VIN_ON,
	EV_VIN_OFF,
	EV_ARMED,    /* MSP reports armed */
	EV_DISARMED, /* MSP reports disarmed */
	EV_IMPACT,   /* accelerometer threshold */
	EV_CMD_FIND, /* arg: seconds, 0 stops */
	EV_CMD_SILENCE,
};

int modes_init(void);
/* Thread- and ISR-safe: queues the event for the system work queue. */
void modes_post(enum mode_event ev, uint8_t arg);
