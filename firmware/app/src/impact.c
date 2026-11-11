/* SPDX-License-Identifier: MIT */
#include "impact.h"
#include "modes.h"

#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/pm/device.h>

LOG_MODULE_REGISTER(impact, LOG_LEVEL_INF);

#define HPIS1 0x01 /* CTRL2: high-pass filter on the INT1 function, removes gravity */

static const struct device *const accel = DEVICE_DT_GET(DT_ALIAS(accel0));
static bool enabled = true; /* the driver leaves the sensor running after init */

static const struct sensor_trigger trig = {
	.type = SENSOR_TRIG_DELTA,
	.chan = SENSOR_CHAN_ACCEL_XYZ,
};

static void on_impact(const struct device *dev, const struct sensor_trigger *t)
{
	LOG_INF("impact");
	modes_post(EV_IMPACT, 0);
}

int impact_init(void)
{
	/* mg -> micro m/s^2 */
	int64_t ums2 = (int64_t)CONFIG_CRICKET_IMPACT_MG * 9807;
	struct sensor_value th = {.val1 = ums2 / 1000000, .val2 = ums2 % 1000000};
	struct sensor_value dur = {.val1 = 0}; /* one sample above the threshold */
	struct sensor_value hp = {.val1 = HPIS1};
	int err;

	if (!device_is_ready(accel)) {
		LOG_ERR("accelerometer not ready");
		return -ENODEV;
	}
	err = sensor_attr_set(accel, SENSOR_CHAN_ACCEL_XYZ, SENSOR_ATTR_CONFIGURATION, &hp);
	err = err ?: sensor_attr_set(accel, SENSOR_CHAN_ACCEL_XYZ, SENSOR_ATTR_SLOPE_TH, &th);
	err = err ?: sensor_attr_set(accel, SENSOR_CHAN_ACCEL_XYZ, SENSOR_ATTR_SLOPE_DUR, &dur);
	err = err ?: sensor_trigger_set(accel, &trig, on_impact);
	if (err) {
		LOG_ERR("accelerometer setup failed (%d)", err);
		return err;
	}
	LOG_INF("impact threshold %d mg", CONFIG_CRICKET_IMPACT_MG);
	return 0;
}

void impact_enable(bool on)
{
	if (on == enabled) {
		return;
	}
	enabled = on;
	pm_device_action_run(accel, on ? PM_DEVICE_ACTION_RESUME : PM_DEVICE_ACTION_SUSPEND);
}
