/* SPDX-License-Identifier: MIT */
/*
 * Mode state machine. Everything runs on the system work queue.
 *
 *   5 V present            -> ON_DRONE (radio off while armed)
 *   5 V lost: armed or impact within IMPACT_WINDOW -> ALARM
 *             disarmed reported by MSP recently    -> STANDBY (battery swap)
 *             no data at all                        -> ESCALATE -> ALARM
 *   ALARM -> BEACON after ALARM_TIME; ESCALATE/ALARM/BEACON -> STANDBY by button or app
 *   battery low -> LOW_BAT, critical -> SHIP; long press -> SHIP
 */
#include "modes.h"
#include "adv.h"
#include "battery.h"
#include "buzzer.h"
#include "gatt.h"
#include "inputs.h"
#include "status.h"

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/logging/log_ctrl.h>
#include <zephyr/sys/poweroff.h>

LOG_MODULE_REGISTER(modes, LOG_LEVEL_INF);

#define IMPACT_WINDOW_MS    (10 * 1000)
#define MSP_FRESH_MS        (5 * 1000)
#define ESCALATE_TIME_MS    (45 * 1000)
#define ESCALATE_CHIRP_MS   (5 * 1000)
#define ALARM_TIME_MS       (45 * 60 * 1000)
#define ALARM_BEEP_MS       (5 * 1000)
#define BEACON_BEEP_MS      (60 * 1000)
#define REFRESH_MS          (10 * 1000)
#define BATTERY_CHECK_MS    (60 * 1000)
#define LOW_BAT_MV          3400
#define CRITICAL_BAT_MV     3200

struct event {
	uint8_t ev;
	uint8_t arg;
};

K_MSGQ_DEFINE(events, sizeof(struct event), 8, 1);

static void event_fn(struct k_work *w);
static void tick_fn(struct k_work *w);
static K_WORK_DEFINE(event_work, event_fn);
static K_WORK_DELAYABLE_DEFINE(tick_work, tick_fn);

static enum cricket_mode mode;
static int64_t mode_since;
static int64_t last_beep;
static int64_t last_refresh;
static int64_t last_battery_check = -BATTERY_CHECK_MS; /* check on the first tick */
static bool armed;
static int64_t msp_seen_at = -1;
static int64_t impact_at = -1;

static bool recent(int64_t at, int64_t window)
{
	return at >= 0 && k_uptime_get() - at <= window;
}

static void publish(void)
{
	adv_refresh();
	gatt_notify_status();
	last_refresh = k_uptime_get();
}

static void enter(enum cricket_mode m)
{
	if (m == mode) {
		return;
	}
	LOG_INF("%s -> %s", status_mode_name(mode), status_mode_name(m));
	mode = m;
	mode_since = k_uptime_get();
	last_beep = 0;
	status_set_mode(m);

	if (m == MODE_ON_DRONE || m == MODE_STANDBY || m == MODE_LOW_BAT) {
		if (buzzer_active()) {
			buzzer_play(BUZZ_OFF, 0);
		}
	}
	adv_apply(m, armed);
	publish();
	k_work_reschedule(&tick_work, K_NO_WAIT);
}

static void poweroff_fn(struct k_work *w)
{
	buzzer_play(BUZZ_OFF, 0);
	inputs_prepare_wakeup();
	LOG_INF("System OFF");
	LOG_PANIC();
	sys_poweroff();
}

static K_WORK_DELAYABLE_DEFINE(poweroff_work, poweroff_fn);

/* The goodbye beep plays on this work queue, so power off from a delayed work item. */
static void ship(void)
{
	LOG_INF("%s -> SHIP", status_mode_name(mode));
	mode = MODE_SHIP;
	status_set_mode(MODE_SHIP);
	k_work_cancel_delayable(&tick_work);
	adv_stop_all();
	buzzer_play(BUZZ_BYE, 0);
	k_work_reschedule(&poweroff_work, K_MSEC(800));
}

static void power_lost(void)
{
	bool was_armed = armed && recent(msp_seen_at, MSP_FRESH_MS);
	bool impact = recent(impact_at, IMPACT_WINDOW_MS);

	status_update_flags((was_armed ? FLAG_WAS_ARMED : 0) | (impact ? FLAG_IMPACT : 0),
			    FLAG_VIN | FLAG_WAS_ARMED | FLAG_IMPACT);
	if (was_armed || impact) {
		enter(MODE_ALARM);
	} else if (recent(msp_seen_at, MSP_FRESH_MS)) {
		enter(MODE_STANDBY);
	} else {
		enter(MODE_ESCALATE);
	}
}

static bool alarming(void)
{
	return mode == MODE_ESCALATE || mode == MODE_ALARM || mode == MODE_BEACON;
}

static void handle(enum mode_event ev, uint8_t arg)
{
	if (mode == MODE_SHIP) {
		return;
	}
	switch (ev) {
	case EV_BTN_SHORT:
	case EV_CMD_SILENCE:
		if (alarming()) {
			enter(MODE_STANDBY);
			buzzer_play(BUZZ_ACK, 0);
		} else if (ev == EV_BTN_SHORT) {
			buzzer_play(BUZZ_TEST, 0);
		}
		break;
	case EV_BTN_HOLD3:
		LOG_INF("pairing requested (not implemented yet)");
		buzzer_play(BUZZ_ACK, 0);
		break;
	case EV_BTN_HOLD8:
		if (inputs_vin_present()) {
			/* 5 V would wake it at once; storage mode is for a beacon off the drone */
			LOG_INF("SHIP refused: 5 V present");
			buzzer_play(BUZZ_ACK, 0);
		} else {
			ship();
		}
		break;
	case EV_VIN_ON:
		status_update_flags(FLAG_VIN, FLAG_WAS_ARMED | FLAG_IMPACT);
		enter(MODE_ON_DRONE);
		break;
	case EV_VIN_OFF:
		if (mode == MODE_ON_DRONE) {
			power_lost();
		}
		break;
	case EV_ARMED:
	case EV_DISARMED:
		armed = ev == EV_ARMED;
		msp_seen_at = k_uptime_get();
		if (mode == MODE_ON_DRONE) {
			adv_apply(mode, armed);
		}
		break;
	case EV_IMPACT:
		impact_at = k_uptime_get();
		break;
	case EV_CMD_FIND:
		if (mode != MODE_ON_DRONE || !armed) {
			buzzer_play(BUZZ_FIND, arg);
		}
		break;
	}
	publish();
}

static void event_fn(struct k_work *w)
{
	struct event e;

	while (k_msgq_get(&events, &e, K_NO_WAIT) == 0) {
		handle(e.ev, e.arg);
	}
}

void modes_post(enum mode_event ev, uint8_t arg)
{
	struct event e = {.ev = ev, .arg = arg};

	if (k_msgq_put(&events, &e, K_NO_WAIT)) {
		LOG_WRN("event queue full, dropped %d", ev);
		return;
	}
	k_work_submit(&event_work);
}

static void check_battery(int64_t now)
{
	int mv = battery_mv();

	last_battery_check = now;
	if (mv <= 0) {
		return; /* not measured (DK) */
	}
	status_set_battery(mv);
	if (mode == MODE_ON_DRONE) {
		return;
	}
	if (mv < CRITICAL_BAT_MV) {
		ship();
	} else if (mv < LOW_BAT_MV) {
		enter(MODE_LOW_BAT);
	}
}

static void tick_fn(struct k_work *w)
{
	int64_t now = k_uptime_get();
	int64_t in_mode = now - mode_since;
	k_timeout_t next = K_SECONDS(10);

	{
		bool charging = inputs_charging();

		buzzer_set_charging(charging);
		status_update_flags(charging ? FLAG_CHARGING : 0, charging ? 0 : FLAG_CHARGING);
	}

	if (now - last_battery_check >= BATTERY_CHECK_MS) {
		check_battery(now);
		if (mode == MODE_SHIP) {
			return;
		}
	}

	switch (mode) {
	case MODE_ESCALATE:
		if (in_mode >= ESCALATE_TIME_MS) {
			enter(MODE_ALARM);
			return;
		}
		if (now - last_beep >= ESCALATE_CHIRP_MS) {
			buzzer_play(BUZZ_CHIRP, 0);
			last_beep = now;
		}
		next = K_SECONDS(1);
		break;
	case MODE_ALARM:
		if (in_mode >= ALARM_TIME_MS) {
			enter(MODE_BEACON);
			return;
		}
		if (now - last_beep >= ALARM_BEEP_MS && !buzzer_active()) {
			buzzer_play(BUZZ_ALARM, 0);
			last_beep = now;
		}
		next = K_SECONDS(1);
		break;
	case MODE_BEACON:
		if (now - last_beep >= BEACON_BEEP_MS && !buzzer_active()) {
			buzzer_play(BUZZ_BEACON, 0);
			last_beep = now;
		}
		break;
	default:
		break;
	}

	if (now - last_refresh >= REFRESH_MS) {
		publish();
	}
	k_work_reschedule(&tick_work, next);
}

int modes_init(void)
{
	int err = inputs_init();

	if (err) {
		return err;
	}
	/*
	 * Power-up without 5 V is a battery being connected: stay quiet (D-12).
	 * mode starts as SHIP so that enter() applies the first mode in full.
	 */
	mode = MODE_SHIP;
	if (inputs_vin_present()) {
		status_update_flags(FLAG_VIN, 0);
		enter(MODE_ON_DRONE);
	} else {
		enter(MODE_STANDBY);
	}
	return 0;
}
