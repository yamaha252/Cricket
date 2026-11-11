/* SPDX-License-Identifier: MIT */
/* Cricket tag: BLE crash beacon for drones. Own search mechanism first (D-32). */
#include "adv.h"
#include "battery.h"
#include "buzzer.h"
#include "dfu.h"
#include "modes.h"
#include "pair.h"
#include "status.h"
#include "wdog.h"

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/settings/settings.h>

LOG_MODULE_REGISTER(main, LOG_LEVEL_INF);

int main(void)
{
	int err;

	status_init();
	LOG_INF("Cricket tag, id %08x", status_id());

	err = wdog_init();
	if (err) {
		LOG_WRN("watchdog init failed (%d)", err);
	}

	err = battery_init();
	if (err) {
		LOG_WRN("battery init failed (%d)", err);
	}
	err = buzzer_init();
	if (err) {
		return err;
	}
	err = bt_enable(NULL);
	if (err) {
		LOG_ERR("Bluetooth init failed (%d)", err);
		return err;
	}
	/* bonds from the settings partition */
	err = settings_load();
	if (err) {
		LOG_WRN("settings load failed (%d)", err);
	}
	err = pair_init();
	if (err) {
		return err;
	}
	err = adv_init();
	if (err) {
		return err;
	}
	err = modes_init();
	if (err) {
		return err;
	}
	return dfu_init();
}
