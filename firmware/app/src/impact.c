/* SPDX-License-Identifier: MIT */
#include "impact.h"
#include "modes.h"

#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/pm/device.h>

LOG_MODULE_REGISTER(impact, LOG_LEVEL_INF);

#define HPIS1 0x01 /* CTRL2: high-pass filter on the INT1 function, removes gravity */

/*
 * Free fall: |a| below FF_MG for FF_MS. The output registers are not
 * high-pass filtered (FDS off), so they keep gravity. Polled while 5 V is
 * present; in the air an armed drone also dips near 0 g (dives), so modes.c
 * only counts a fall around a disarm.
 */
#define FF_MG      400
#define FF_MS      250
#define FF_POLL_MS 20
#define FF_SAMPLES (FF_MS / FF_POLL_MS)

static const struct device *const accel = DEVICE_DT_GET(DT_ALIAS(accel0));
static bool enabled = true; /* the driver leaves the sensor running after init */
static int low_count;

static void ff_fn(struct k_work *w);
static K_WORK_DELAYABLE_DEFINE(ff_work, ff_fn);

static const struct sensor_trigger trig = {
	.type = SENSOR_TRIG_DELTA,
	.chan = SENSOR_CHAN_ACCEL_XYZ,
};

static void on_impact(const struct device *dev, const struct sensor_trigger *t)
{
	LOG_INF("impact");
	modes_post(EV_IMPACT, 0);
}

static int64_t mm_s2(const struct sensor_value *v)
{
	return (int64_t)v->val1 * 1000 + v->val2 / 1000;
}

static void ff_fn(struct k_work *w)
{
	const int64_t lim = (int64_t)FF_MG * 9807 / 1000; /* mm/s^2 */
	struct sensor_value v[3];
	int64_t sq;

	if (!enabled) {
		return;
	}
	if (sensor_sample_fetch_chan(accel, SENSOR_CHAN_ACCEL_XYZ) == 0 &&
	    sensor_channel_get(accel, SENSOR_CHAN_ACCEL_XYZ, v) == 0) {
		sq = mm_s2(&v[0]) * mm_s2(&v[0]) + mm_s2(&v[1]) * mm_s2(&v[1]) +
		     mm_s2(&v[2]) * mm_s2(&v[2]);
		if (sq < lim * lim) {
			if (++low_count == FF_SAMPLES) {
				LOG_INF("free fall");
				modes_post(EV_FREEFALL, 0);
			}
		} else {
			low_count = 0;
		}
	}
	k_work_reschedule(&ff_work, K_MSEC(FF_POLL_MS));
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
	k_work_reschedule(&ff_work, K_MSEC(FF_POLL_MS));
	return 0;
}

void impact_enable(bool on)
{
	if (on == enabled) {
		return;
	}
	enabled = on;
	if (on) {
		pm_device_action_run(accel, PM_DEVICE_ACTION_RESUME);
		low_count = 0;
		k_work_reschedule(&ff_work, K_MSEC(FF_POLL_MS));
	} else {
		k_work_cancel_delayable(&ff_work);
		pm_device_action_run(accel, PM_DEVICE_ACTION_SUSPEND);
	}
}
