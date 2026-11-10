/* SPDX-License-Identifier: MIT */
/*
 * Button: short press, hold 3 s (pairing), hold 8 s (SHIP); concept.md, «Кнопка».
 * On the DK (CONFIG_CRICKET_DK_SIM) buttons 1-3 stand in for 5 V presence,
 * the MSP armed state and an accelerometer impact.
 */
#include "inputs.h"
#include "modes.h"

#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(inputs, LOG_LEVEL_INF);

#define DEBOUNCE_MS 30
#define HOLD_PAIR_MS 3000
#define HOLD_SHIP_MS 8000

struct button {
	struct gpio_dt_spec spec;
	struct gpio_callback cb;
	struct k_work_delayable debounce;
	bool pressed;
	int64_t pressed_at;
	void (*changed)(struct button *b);
};

static bool vin_present;

static void user_changed(struct button *b)
{
	int64_t held;

	if (b->pressed) {
		b->pressed_at = k_uptime_get();
		return;
	}
	held = k_uptime_get() - b->pressed_at;
	if (held >= HOLD_SHIP_MS) {
		modes_post(EV_BTN_HOLD8, 0);
	} else if (held >= HOLD_PAIR_MS) {
		modes_post(EV_BTN_HOLD3, 0);
	} else {
		modes_post(EV_BTN_SHORT, 0);
	}
}

static struct button user = {
	.spec = GPIO_DT_SPEC_GET(DT_ALIAS(user_button), gpios),
	.changed = user_changed,
};

#ifdef CONFIG_CRICKET_DK_SIM

static bool sim_armed;

static void sim_vin_changed(struct button *b)
{
	if (b->pressed) {
		vin_present = !vin_present;
		LOG_INF("sim: 5 V %s", vin_present ? "on" : "off");
		modes_post(vin_present ? EV_VIN_ON : EV_VIN_OFF, 0);
	}
}

static void sim_armed_changed(struct button *b)
{
	if (b->pressed) {
		sim_armed = !sim_armed;
		LOG_INF("sim: MSP %s", sim_armed ? "armed" : "disarmed");
		modes_post(sim_armed ? EV_ARMED : EV_DISARMED, 0);
	}
}

static void sim_impact_changed(struct button *b)
{
	if (b->pressed) {
		LOG_INF("sim: impact");
		modes_post(EV_IMPACT, 0);
	}
}

static struct button sims[] = {
	{.spec = GPIO_DT_SPEC_GET(DT_ALIAS(sim_vin), gpios), .changed = sim_vin_changed},
	{.spec = GPIO_DT_SPEC_GET(DT_ALIAS(sim_armed), gpios), .changed = sim_armed_changed},
	{.spec = GPIO_DT_SPEC_GET(DT_ALIAS(sim_impact), gpios), .changed = sim_impact_changed},
};

#endif

static void debounce_fn(struct k_work *w)
{
	struct button *b = CONTAINER_OF(k_work_delayable_from_work(w), struct button, debounce);
	bool pressed = gpio_pin_get_dt(&b->spec) > 0;

	if (pressed != b->pressed) {
		b->pressed = pressed;
		b->changed(b);
	}
}

static void isr(const struct device *dev, struct gpio_callback *cb, uint32_t pins)
{
	struct button *b = CONTAINER_OF(cb, struct button, cb);

	k_work_reschedule(&b->debounce, K_MSEC(DEBOUNCE_MS));
}

static int button_setup(struct button *b)
{
	int err;

	if (!gpio_is_ready_dt(&b->spec)) {
		return -ENODEV;
	}
	err = gpio_pin_configure_dt(&b->spec, GPIO_INPUT);
	if (err) {
		return err;
	}
	k_work_init_delayable(&b->debounce, debounce_fn);
	gpio_init_callback(&b->cb, isr, BIT(b->spec.pin));
	err = gpio_add_callback_dt(&b->spec, &b->cb);
	if (err) {
		return err;
	}
	return gpio_pin_interrupt_configure_dt(&b->spec, GPIO_INT_EDGE_BOTH);
}

int inputs_init(void)
{
	int err = button_setup(&user);

	if (err) {
		LOG_ERR("user button setup failed (%d)", err);
		return err;
	}
#ifdef CONFIG_CRICKET_DK_SIM
	for (int i = 0; i < ARRAY_SIZE(sims); i++) {
		err = button_setup(&sims[i]);
		if (err) {
			LOG_ERR("sim button %d setup failed (%d)", i + 1, err);
			return err;
		}
	}
	LOG_INF("DK simulation: Button1 = 5 V, Button2 = armed, Button3 = impact");
#endif
	return 0;
}

bool inputs_vin_present(void)
{
	return vin_present;
}

void inputs_prepare_wakeup(void)
{
	gpio_pin_interrupt_configure_dt(&user.spec, GPIO_INT_LEVEL_ACTIVE);
}
