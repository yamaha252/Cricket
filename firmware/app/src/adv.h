/* SPDX-License-Identifier: MIT */
/* Cricket advertising sets: Coded S8 (extended) and 1M (legacy), both connectable. */
#pragma once

#include <stdbool.h>
#include "status.h"

int adv_init(void);
/* Set intervals for the mode; armed on the drone silences the radio (ELRS coexistence). */
void adv_apply(enum cricket_mode mode, bool armed);
/* Push current status into both sets' advertising data. */
void adv_refresh(void);
/* Re-read config.c settings (TX power, name, intervals) and restart the sets. */
void adv_reload(void);
void adv_stop_all(void);
