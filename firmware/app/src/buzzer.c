/* SPDX-License-Identifier: MIT */
#include "buzzer.h"
#include "status.h"

#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/pwm.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(buzzer, LOG_LEVEL_INF);

static const struct pwm_dt_spec pwm = PWM_DT_SPEC_GET(DT_ALIAS(buzzer_pwm));
static const struct gpio_dt_spec flash = GPIO_DT_SPEC_GET(DT_ALIAS(flash_led), gpios);

/*
 * PAM8904E gain: EN1 low = 1x, high = 3x (EN2 tied to VBAT, D-28). Optional, absent on the DK.
 * 3x on a full battery reaches the 25 Vpp limit of CPT-1117-83: use 1x while charging (firmware/README.md).
 */
#if DT_NODE_HAS_PROP(DT_PATH(zephyr_user), buz_en1_gpios)
static const struct gpio_dt_spec en1 = GPIO_DT_SPEC_GET(DT_PATH(zephyr_user), buz_en1_gpios);
#define HAS_EN1 1
#else
#define HAS_EN1 0
#endif

struct step {
	uint16_t on_ms;
	uint16_t off_ms;
};

struct pattern {
	const struct step *steps;
	uint8_t count;
	bool loud;
	bool flash;
};

#define PATTERN(name, loud_, flash_, ...)                                                    \
	static const struct step name##_steps[] = {__VA_ARGS__};                             \
	static const struct pattern name = {name##_steps, ARRAY_SIZE(name##_steps), loud_, flash_}

PATTERN(p_test, false, true, {150, 0});
PATTERN(p_ack, false, true, {60, 80}, {60, 0});
PATTERN(p_chirp, false, false, {40, 0});
PATTERN(p_alarm, true, true, {150, 100}, {150, 100}, {150, 0});
PATTERN(p_beacon, true, true, {200, 0});
PATTERN(p_find, true, true, {200, 300});
PATTERN(p_bye, false, true, {150, 100}, {300, 0});

static const struct pattern *patterns[] = {
	[BUZZ_OFF] = NULL,     [BUZZ_TEST] = &p_test,     [BUZZ_ACK] = &p_ack,
	[BUZZ_CHIRP] = &p_chirp, [BUZZ_ALARM] = &p_alarm, [BUZZ_BEACON] = &p_beacon,
	[BUZZ_FIND] = &p_find, [BUZZ_BYE] = &p_bye,
};

static const struct pattern *cur;
static uint8_t step;
static bool tone_on;
static int64_t find_until_ms;
static bool charging;

static void work_fn(struct k_work *w);
static K_WORK_DELAYABLE_DEFINE(work, work_fn);

static void output(bool on, bool loud, bool with_flash)
{
	uint32_t period = PWM_HZ(CONFIG_CRICKET_BUZZER_FREQ_HZ);

#if HAS_EN1
	gpio_pin_set_dt(&en1, on && loud && !charging);
#else
	ARG_UNUSED(loud);
#endif
	pwm_set_dt(&pwm, period, on ? period / 2 : 0);
	gpio_pin_set_dt(&flash, on && with_flash);
	tone_on = on;
}

static void stop(void)
{
	output(false, false, false);
	cur = NULL;
	status_update_flags(0, FLAG_BUZZING);
}

static void work_fn(struct k_work *w)
{
	const struct step *s;

	if (!cur) {
		return;
	}
	s = &cur->steps[step];

	if (!tone_on) {
		output(true, cur->loud, cur->flash);
		k_work_reschedule(&work, K_MSEC(s->on_ms));
		return;
	}

	output(false, false, false);
	step++;
	if (step == cur->count) {
		if (cur == &p_find && k_uptime_get() < find_until_ms) {
			step = 0;
		} else {
			stop();
			return;
		}
	}
	k_work_reschedule(&work, K_MSEC(s->off_ms));
}

int buzzer_init(void)
{
	if (!pwm_is_ready_dt(&pwm) || !gpio_is_ready_dt(&flash)) {
		LOG_ERR("buzzer or flash LED not ready");
		return -ENODEV;
	}
	gpio_pin_configure_dt(&flash, GPIO_OUTPUT_INACTIVE);
#if HAS_EN1
	gpio_pin_configure_dt(&en1, GPIO_OUTPUT_INACTIVE);
#endif
	output(false, false, false);
	return 0;
}

void buzzer_play(enum buzz_pattern p, uint8_t duration_s)
{
	k_work_cancel_delayable(&work);
	stop();
	if (p == BUZZ_OFF || (p == BUZZ_FIND && duration_s == 0)) {
		return;
	}
	cur = patterns[p];
	step = 0;
	find_until_ms = k_uptime_get() + duration_s * 1000LL;
	status_update_flags(FLAG_BUZZING, 0);
	k_work_reschedule(&work, K_NO_WAIT);
}

bool buzzer_active(void)
{
	return cur != NULL;
}

void buzzer_set_charging(bool c)
{
	charging = c;
}
