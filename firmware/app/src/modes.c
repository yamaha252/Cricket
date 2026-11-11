/* SPDX-License-Identifier: MIT */
/*
 * Mode state machine. Everything runs on the system work queue.
 *
 *   5 V present            -> ON_DRONE (radio off while armed)
 *   flight ended abnormally, 5 V still present -> ESCALATE -> ALARM:
 *             disarmed with failsafe active, disarmed in the air (free fall,
 *             impact or GPS speed around the disarm), or no RC link for
 *             LINK_LOST_TIME after a flight
 *   5 V lost: armed, impact within IMPACT_WINDOW, or failsafe after a flight
 *                                                   -> ALARM
 *             disarmed reported by MSP recently    -> STANDBY (battery swap)
 *             no data at all                        -> ESCALATE -> ALARM
 *   ALARM -> BEACON after ALARM_TIME; ESCALATE/ALARM/BEACON -> STANDBY by button or
 *   app, or back to ON_DRONE when the BEEPER switch goes off or the drone is armed
 *   BEEPER switch on (disarmed): beep like FIND until it goes off
 *   5 V back within VIN_GLITCH after a loss in flight: the alarm stays unless the
 *   FC reports armed again (it did not reboot); MSP silent while armed and then
 *   disarmed: the FC restarted in flight -> ESCALATE
 *   radio off while flying (armed by MSP, or motor vibration without MSP), except
 *   in failsafe or without RC link: then the drone may be flying away
 *   5 V comes: preflight beep (tag battery, MSP answer)
 *   battery low -> LOW_BAT, critical -> SHIP; long press -> SHIP
 */
#include "modes.h"
#include "adv.h"
#include "battery.h"
#include "buzzer.h"
#include "config.h"
#include "dfu.h"
#include "gatt.h"
#include "impact.h"
#include "inputs.h"
#include "msp.h"
#include "pair.h"
#include "status.h"
#include "wdog.h"

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
#define DISARM_LEAD_MS      1500  /* free fall may be seen before MSP reports the disarm */
#define DISARM_TAIL_MS      (5 * 1000) /* fall or impact after the disarm */
#define LINK_LOST_TIME_MS   (30 * 1000)
#define FIND_SWITCH_S       60    /* BEEPER switch: FIND repeated while it stays on */
#define FC_RESTART_GAP_MS   2000  /* MSP silent this long while armed: FC rebooted */
#define VIN_GLITCH_MS       (10 * 1000)
#define FLYAWAY_REFRESH_MS  (2 * 1000)
#define PREFLIGHT_DELAY_MS  (5 * 1000) /* time for MSP to answer after 5 V comes */
#define PREFLIGHT_GAP_MS    (2500)
#define PREFLIGHT_LOW_MV    3700  /* less is not enough for a long alarm */
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
static uint8_t msp;           /* last MSP_* bits */
static int64_t msp_seen_at = -1;
static int64_t impact_at = -1;
static int64_t freefall_at = -1;
static bool flew;             /* armed since 5 V came, and no alarm raised for it yet */
static int64_t disarmed_at = -1;
static bool moving_at_disarm;
static int64_t failsafe_at = -1; /* MSP_FAILSAFE last seen while armed */
static int64_t rxloss_since = -1;
static bool vibrating;        /* motors running, from the accelerometer */
static bool radio_quiet = true;
static int64_t vin_lost_at = -1;
static bool vin_lost_flying;
static uint16_t pre_vin_mv;   /* tag battery before 5 V came, for the preflight check */
static uint16_t mv_without_vin; /* last battery reading while not charging */
static uint8_t preflight_step;

static void preflight_fn(struct k_work *w);
static K_WORK_DELAYABLE_DEFINE(preflight_work, preflight_fn);

static bool recent(int64_t at, int64_t window)
{
	return at >= 0 && k_uptime_get() - at <= window;
}

/* MSP and the accelerometer run while 5 V is present: they cost the FC's power */
static void sensors(bool on)
{
	/* both are no-ops when already in that state */
	if (on) {
		msp_start();
	} else {
		msp_stop();
	}
	impact_enable(on);
}

static bool msp_fresh(void)
{
	return recent(msp_seen_at, MSP_FRESH_MS);
}

/* In the air as far as the tag can tell: MSP armed, or motor vibration without MSP */
static bool flying(void)
{
	return msp_fresh() ? armed : vibrating;
}

/* Armed but without RC link: failsafe or a flyaway, the radio is free */
static bool flying_lost(void)
{
	return msp_fresh() && armed && (msp & (MSP_FAILSAFE | MSP_RXLOSS));
}

static bool quiet_wanted(void)
{
	return mode == MODE_ON_DRONE && flying() && !flying_lost();
}

static void update_radio(void)
{
	bool q = quiet_wanted();

	if (q != radio_quiet) {
		radio_quiet = q;
		adv_apply(mode, q);
		if (mode == MODE_ON_DRONE && !q && flying_lost()) {
			LOG_INF("armed without RC link: radio on");
		}
	}
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
	sensors(m != MODE_SHIP && inputs_vin_present());
	mode = m;
	mode_since = k_uptime_get();
	last_beep = 0;
	status_set_mode(m);

	if (m == MODE_ON_DRONE || m == MODE_STANDBY || m == MODE_LOW_BAT) {
		if (buzzer_active()) {
			buzzer_play(BUZZ_OFF, 0);
		}
	}
	radio_quiet = quiet_wanted();
	adv_apply(m, radio_quiet);
	publish();
	k_work_reschedule(&tick_work, K_NO_WAIT);
}

static void poweroff_fn(struct k_work *w)
{
	wdog_stop();
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
	sensors(false);
	adv_stop_all();
	buzzer_play(BUZZ_BYE, 0);
	k_work_reschedule(&poweroff_work, K_MSEC(800));
}

/* Free fall around the last disarm: the drone was disarmed in the air */
static bool fell_at_disarm(void)
{
	return disarmed_at >= 0 && freefall_at >= disarmed_at - DISARM_LEAD_MS;
}

static void power_lost(void)
{
	bool fresh = msp_fresh();
	bool was_armed = flying();
	/* link loss alone is not enough: the pilot may switch the transmitter off first */
	bool lost = flew && fresh && (msp & MSP_FAILSAFE);
	bool impact = recent(impact_at, IMPACT_WINDOW_MS) ||
		      (recent(freefall_at, IMPACT_WINDOW_MS) && fell_at_disarm());

	status_update_flags((was_armed || lost ? FLAG_WAS_ARMED : 0) | (impact ? FLAG_IMPACT : 0),
			    FLAG_VIN | FLAG_WAS_ARMED | FLAG_IMPACT);
	vin_lost_at = k_uptime_get();
	vin_lost_flying = was_armed;
	if (was_armed || impact || lost) {
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

/* The drone is down but still powered: alarm now instead of waiting for 5 V to go */
static void flight_lost(const char *why, bool impact)
{
	LOG_INF("flight ended abnormally: %s", why);
	flew = false; /* one alarm per flight */
	status_update_flags(FLAG_WAS_ARMED | (impact ? FLAG_IMPACT : 0), 0);
	enter(MODE_ESCALATE);
}

static bool fc_restarted; /* MSP went silent while armed and came back disarmed */

/* After a disarm, and on every fall or impact shortly after it */
static void check_disarm(void)
{
	if (mode != MODE_ON_DRONE || armed || !flew || !recent(disarmed_at, DISARM_TAIL_MS)) {
		return;
	}
	if (fc_restarted) {
		flight_lost("FC restarted in flight", false);
	} else if ((msp & MSP_FAILSAFE) || failsafe_at >= disarmed_at - DISARM_LEAD_MS) {
		flight_lost("failsafe", false);
	} else if (fell_at_disarm()) {
		flight_lost("disarmed in a fall", true);
	} else if (moving_at_disarm) {
		flight_lost("disarmed while moving", false);
	} else if (impact_at >= disarmed_at - IMPACT_WINDOW_MS) {
		flight_lost("impact around the disarm", true);
	}
}

static void msp_changed(uint8_t bits)
{
	int64_t now = k_uptime_get();
	bool was_armed = armed;
	bool beeper_was = msp & MSP_BEEPER;
	bool gap = was_armed && msp_seen_at >= 0 && now - msp_seen_at > FC_RESTART_GAP_MS;

	msp_seen_at = now;
	msp = bits;
	armed = bits & MSP_ARMED;

	if (armed) {
		flew = true;
		rxloss_since = -1;
		if (bits & MSP_FAILSAFE) {
			failsafe_at = now;
		}
		if (!was_armed && alarming()) {
			enter(MODE_ON_DRONE); /* flying again */
		}
	} else {
		if (bits & MSP_RXLOSS) {
			if (rxloss_since < 0) {
				rxloss_since = now;
			}
		} else {
			rxloss_since = -1;
		}
	}
	update_radio();
	if (was_armed && !armed) {
		disarmed_at = now;
		fc_restarted = gap;
		moving_at_disarm = bits & MSP_MOVING;
		check_disarm();
	}

	/* BEEPER switch from the transmitter: beep while on, off acknowledges an alarm */
	if (armed) {
		return;
	}
	if (bits & MSP_BEEPER) {
		if (!beeper_was || !buzzer_active()) {
			buzzer_play(BUZZ_FIND, FIND_SWITCH_S);
		}
	} else if (beeper_was) {
		buzzer_play(BUZZ_OFF, 0);
		if (alarming()) {
			flew = false;
			enter(MODE_ON_DRONE);
		}
	}
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
		pair_open();
		buzzer_play(BUZZ_ACK, 0);
		break;
	case EV_PAIRED:
		buzzer_play(BUZZ_TEST, 0);
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
		if (alarming() && vin_lost_flying && recent(vin_lost_at, VIN_GLITCH_MS)) {
			/*
			 * 5 V dropped in flight and came back: a brownout or a bouncing
			 * battery. Keep the alarm; MSP reporting armed again ends it.
			 */
			LOG_INF("5 V back after a loss in flight, alarm kept");
			armed = false;
			msp = 0;
			msp_seen_at = -1;
			vibrating = false;
			status_update_flags(FLAG_VIN, 0);
			sensors(true);
			break;
		}
		/* Forget the last flight: until MSP answers the drone counts as disarmed */
		pre_vin_mv = mv_without_vin > 0 ? mv_without_vin : MAX(battery_mv(), 0);
		armed = false;
		msp = 0;
		vibrating = false;
		fc_restarted = false;
		vin_lost_flying = false;
		flew = false;
		msp_seen_at = -1;
		impact_at = -1;
		freefall_at = -1;
		disarmed_at = -1;
		failsafe_at = -1;
		rxloss_since = -1;
		status_update_flags(FLAG_VIN, FLAG_WAS_ARMED | FLAG_IMPACT);
		enter(MODE_ON_DRONE);
		preflight_step = 0;
		k_work_reschedule(&preflight_work, K_MSEC(PREFLIGHT_DELAY_MS));
		break;
	case EV_VIN_OFF:
		if (mode == MODE_ON_DRONE) {
			power_lost();
		} else {
			/* an alarm raised on 5 V goes on from the battery */
			status_update_flags(0, FLAG_VIN);
			sensors(false);
		}
		break;
	case EV_MSP:
		/* Repeated every second as a heartbeat; acts only on changes */
		if (arg == msp && msp_seen_at >= 0) {
			msp_seen_at = k_uptime_get();
			if (!armed && (arg & MSP_BEEPER) && !buzzer_active()) {
				buzzer_play(BUZZ_FIND, FIND_SWITCH_S);
			}
			return;
		}
		msp_changed(arg);
		break;
	case EV_IMPACT:
		impact_at = k_uptime_get();
		check_disarm();
		break;
	case EV_FREEFALL:
		freefall_at = k_uptime_get();
		check_disarm();
		break;
	case EV_VIBRATION:
		vibrating = arg;
		if (vibrating && alarming() && inputs_vin_present() && !msp_fresh()) {
			enter(MODE_ON_DRONE); /* motors running again: flying, not lost */
		}
		update_radio();
		break;
	case EV_DFU:
		dfu_open();
		if (arg) {
			/* physical access: let a new phone bond too, SMP needs a bonded link */
			pair_open();
		}
		buzzer_play(BUZZ_ACK, 0);
		break;
	case EV_CMD_FIND:
		if (mode != MODE_ON_DRONE || !flying()) {
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

/*
 * Preflight check a few seconds after 5 V comes, quiet (charging forces 1x):
 * one beep - all good; three long - tag battery low; two long - no MSP answer.
 */
static void preflight_fn(struct k_work *w)
{
	bool low = pre_vin_mv > 0 && pre_vin_mv < PREFLIGHT_LOW_MV;
	bool no_msp = IS_ENABLED(CONFIG_CRICKET_MSP) && !msp_fresh();

	if (mode != MODE_ON_DRONE || flying() || !config_preflight()) {
		return;
	}
	if (preflight_step == 0) {
		LOG_INF("preflight: battery %u mV%s, MSP %s", pre_vin_mv, low ? " (low)" : "",
			no_msp ? "silent" : "ok");
		if (low) {
			buzzer_play(BUZZ_LOW_BATT, 0);
		} else if (no_msp) {
			buzzer_play(BUZZ_NO_MSP, 0);
		} else {
			buzzer_play(BUZZ_TEST, 0);
		}
		if (low && no_msp) {
			preflight_step = 1;
			k_work_reschedule(&preflight_work, K_MSEC(PREFLIGHT_GAP_MS));
		}
	} else if (no_msp) {
		buzzer_play(BUZZ_NO_MSP, 0);
	}
}

static void check_battery(int64_t now)
{
	int mv = battery_mv();

	last_battery_check = now;
	if (mv <= 0) {
		return; /* not measured (DK) */
	}
	status_set_battery(mv);
	if (!inputs_vin_present()) {
		mv_without_vin = mv;
	}
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

	wdog_feed();

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
	case MODE_ON_DRONE:
		if (!armed && flew && rxloss_since >= 0 && msp_fresh() &&
		    now - rxloss_since >= LINK_LOST_TIME_MS) {
			flight_lost("no RC link after the flight", false);
			return;
		}
		update_radio(); /* MSP may have gone silent */
		if (flying_lost()) {
			/* flyaway: send the latest GPS fix often */
			publish();
			next = K_MSEC(FLYAWAY_REFRESH_MS);
		}
		break;
	case MODE_ESCALATE:
		if (in_mode >= ESCALATE_TIME_MS) {
			enter(MODE_ALARM);
			return;
		}
		if (now - last_beep >= ESCALATE_CHIRP_MS && !buzzer_active()) {
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

	err = err ?: msp_init();
	err = err ?: impact_init();
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
		pre_vin_mv = MAX(battery_mv(), 0); /* already charging: a little optimistic */
		k_work_reschedule(&preflight_work, K_MSEC(PREFLIGHT_DELAY_MS));
	} else {
		enter(MODE_STANDBY);
	}
	return 0;
}
