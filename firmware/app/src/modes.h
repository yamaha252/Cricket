/* SPDX-License-Identifier: MIT */
/* Operating modes, concept.md «Режимы работы». */
#pragma once

#include <stdint.h>
#include <zephyr/sys/util.h>

enum mode_event {
	EV_BTN_SHORT,
	EV_BTN_HOLD3,
	EV_BTN_HOLD8,
	EV_VIN_ON,
	EV_VIN_OFF,
	EV_MSP,      /* arg: MSP_* state bits; on change and every second as a heartbeat */
	EV_IMPACT,   /* accelerometer threshold */
	EV_FREEFALL, /* accelerometer near 0 g long enough to be a fall */
	EV_VIBRATION, /* arg 1: motor vibration started, 0: stopped */
	EV_CMD_FIND, /* arg: seconds, 0 stops */
	EV_CMD_SILENCE,
	EV_DFU,      /* open the firmware update window; arg 1: from the button */
	EV_PAIRED,   /* a phone bonded */
};

/* EV_MSP argument bits, from MSP_STATUS and MSP_RAW_GPS (msp.c) */
#define MSP_ARMED    BIT(0)
#define MSP_BEEPER   BIT(1) /* BEEPER mode switched on from the transmitter */
#define MSP_FAILSAFE BIT(2) /* failsafe active, or crash detected by the FC */
#define MSP_RXLOSS   BIT(3) /* no RC link */
#define MSP_MOVING   BIT(4) /* GPS ground speed above 5 m/s */

int modes_init(void);
/* Thread- and ISR-safe: queues the event for the system work queue. */
void modes_post(enum mode_event ev, uint8_t arg);
