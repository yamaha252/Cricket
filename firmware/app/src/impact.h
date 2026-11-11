/* SPDX-License-Identifier: MIT */
/*
 * Impact detection with the LIS2DH12: high-pass filtered acceleration above
 * CONFIG_CRICKET_IMPACT_MG on INT1 posts EV_IMPACT; |a| near 0 g for 250 ms,
 * polled at 50 Hz, posts EV_FREEFALL; motor vibration posts EV_VIBRATION.
 * Active only while 5 V is present.
 */
#pragma once

#include <stdbool.h>

#ifdef CONFIG_CRICKET_IMPACT
int impact_init(void);
void impact_enable(bool on);
#else
static inline int impact_init(void) { return 0; }
static inline void impact_enable(bool on) { (void)on; }
#endif
