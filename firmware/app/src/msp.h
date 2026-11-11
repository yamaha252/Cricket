/* SPDX-License-Identifier: MIT */
/*
 * MSP v1 client to the flight controller (Betaflight, INAV): armed, BEEPER and
 * FAILSAFE modes and link loss from MSP_STATUS, the GPS fix and ground speed
 * from MSP_RAW_GPS; posted to modes.c as EV_MSP. The FC must run MSP on the UART
 * wired to the tag, 115200 baud.
 */
#pragma once

#ifdef CONFIG_CRICKET_MSP
int msp_init(void);
/* Power the UART and start polling; call while 5 V is present. */
void msp_start(void);
/* Stop polling and suspend the UART so TX does not feed an unpowered FC. */
void msp_stop(void);
#else
static inline int msp_init(void) { return 0; }
static inline void msp_start(void) {}
static inline void msp_stop(void) {}
#endif
