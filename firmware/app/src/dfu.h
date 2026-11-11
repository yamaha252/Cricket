/* SPDX-License-Identifier: MIT */
/*
 * Firmware update over BLE (MCUmgr SMP, MCUboot). SMP commands are accepted
 * only inside a DFU window: opened by holding the button at power-up, it lasts
 * DFU_WINDOW_S and each accepted command extends it.
 */
#pragma once

int dfu_init(void);
void dfu_open(void);
