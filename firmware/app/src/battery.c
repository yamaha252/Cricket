/* SPDX-License-Identifier: MIT */
#include "battery.h"

#include <zephyr/drivers/adc.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(battery, LOG_LEVEL_INF);

#define USER_NODE DT_PATH(zephyr_user)

#if DT_NODE_HAS_PROP(USER_NODE, io_channels)

static const struct adc_dt_spec ch = ADC_DT_SPEC_GET(USER_NODE);

/* VBAT = V_adc * full / output; resistances from zephyr,user (vbat-full-ohms, vbat-output-ohms) */
#define DIV_FULL DT_PROP(USER_NODE, vbat_full_ohms)
#define DIV_OUT  DT_PROP(USER_NODE, vbat_output_ohms)

int battery_init(void)
{
	if (!adc_is_ready_dt(&ch)) {
		return -ENODEV;
	}
	return adc_channel_setup_dt(&ch);
}

int battery_mv(void)
{
	int16_t raw;
	int32_t mv;
	struct adc_sequence seq = {
		.buffer = &raw,
		.buffer_size = sizeof(raw),
	};

	adc_sequence_init_dt(&ch, &seq);
	if (adc_read_dt(&ch, &seq)) {
		return 0;
	}
	mv = raw;
	if (adc_raw_to_millivolts_dt(&ch, &mv)) {
		return 0;
	}
	return (int)((int64_t)mv * DIV_FULL / DIV_OUT);
}

#else

int battery_init(void)
{
	LOG_INF("no VBAT divider, battery not measured");
	return 0;
}

int battery_mv(void)
{
	return 0;
}

#endif
