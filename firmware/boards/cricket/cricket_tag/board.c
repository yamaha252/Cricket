/*
 * SPDX-License-Identifier: MIT
 *
 * P1.02/P1.03 carry I2C to the LIS2DH12, but after reset they are NFC pads
 * (NFCT.PADCONFIG = 1). Zephyr releases them only on nRF54H, so do it here
 * before any driver configures the pins.
 */
#include <zephyr/init.h>
#include <hal/nrf_nfct.h>

static int cricket_tag_init(void)
{
	nrf_nfct_pad_config_enable_set(NRF_NFCT, false);
	return 0;
}

SYS_INIT(cricket_tag_init, PRE_KERNEL_1, 0);
