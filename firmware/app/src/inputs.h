/* SPDX-License-Identifier: MIT */
/* Button and flight-controller inputs, delivered as mode events. */
#pragma once

#include <stdbool.h>

int inputs_init(void);
bool inputs_vin_present(void);
/* Configure the user button to wake the chip from System OFF. */
void inputs_prepare_wakeup(void);
