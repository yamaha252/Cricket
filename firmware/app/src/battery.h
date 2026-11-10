/* SPDX-License-Identifier: MIT */
/* Battery voltage through the VBAT divider (io-channels of zephyr,user). */
#pragma once

int battery_init(void);
/* Battery voltage in mV, or 0 when the board has no divider (nRF54L15 DK). */
int battery_mv(void);
