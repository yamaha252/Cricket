/* SPDX-License-Identifier: MIT */
/*
 * Watchdog (WDT31): resets the chip if the system work queue stops. Fed by the
 * mode tick, which runs at least every 10 s. Keeps counting in sleep; paused
 * only while a debugger halts the CPU. Stopped before System OFF so it does
 * not wake the beacon out of SHIP.
 */
#pragma once

int wdog_init(void);
void wdog_feed(void);
void wdog_stop(void);
