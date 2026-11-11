/* SPDX-License-Identifier: MIT */
#include "wdog.h"

#include <zephyr/drivers/hwinfo.h>
#include <zephyr/drivers/watchdog.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(wdog, LOG_LEVEL_INF);

#define WDOG_TIMEOUT_MS 30000 /* three missed 10-s ticks */

static const struct device *const wdt = DEVICE_DT_GET(DT_ALIAS(watchdog0));
static int channel = -1;

int wdog_init(void)
{
	struct wdt_timeout_cfg cfg = {
		.window = {.min = 0, .max = WDOG_TIMEOUT_MS},
		.flags = WDT_FLAG_RESET_SOC,
	};
	uint32_t cause;

	if (hwinfo_get_reset_cause(&cause) == 0) {
		if (cause & RESET_WATCHDOG) {
			LOG_WRN("previous reset by the watchdog");
		}
		hwinfo_clear_reset_cause();
	}
	if (!device_is_ready(wdt)) {
		LOG_ERR("watchdog not ready");
		return -ENODEV;
	}
	channel = wdt_install_timeout(wdt, &cfg);
	if (channel < 0) {
		LOG_ERR("watchdog timeout install failed (%d)", channel);
		return channel;
	}
	return wdt_setup(wdt, WDT_OPT_PAUSE_HALTED_BY_DBG);
}

void wdog_feed(void)
{
	if (channel >= 0) {
		wdt_feed(wdt, channel);
	}
}

void wdog_stop(void)
{
	if (channel >= 0) {
		int err = wdt_disable(wdt);

		if (err) {
			LOG_WRN("watchdog stop failed (%d)", err);
		}
		channel = -1;
	}
}
