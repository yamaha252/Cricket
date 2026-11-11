/* SPDX-License-Identifier: MIT */
#include "msp.h"
#include "modes.h"
#include "status.h"

#include <zephyr/drivers/uart.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/pm/device.h>
#include <zephyr/sys/byteorder.h>

LOG_MODULE_REGISTER(msp, LOG_LEVEL_INF);

#define MSP_STATUS  101
#define MSP_RAW_GPS 106
#define MSP_BOXIDS  119

/* Permanent box ids in MSP_BOXIDS (Betaflight msp_box.c; INAV uses the same) */
#define BOXARM_ID      0
#define BOXBEEPER_ID   13 /* BEEPER: beeper on from a transmitter switch */
#define BOXFAILSAFE_ID 27 /* reported while failsafe is active (FAILSAFE_MODE) */

/* Betaflight arming disable flags (runtime_config.h), after the mode flags in MSP_STATUS */
#define ARMING_DISABLED_FAILSAFE       BIT(1) /* failsafe landed or dropped the drone */
#define ARMING_DISABLED_RX_FAILSAFE    BIT(2) /* no valid RC data */
#define ARMING_DISABLED_CRASH_DETECTED BIT(6)

#define MOVING_CM_S    500  /* GPS ground speed that means the drone is in the air */
#define GPS_FRESH_MS   1500
#define POLL_MS        250 /* MSP_STATUS rate; GPS every GPS_EVERY polls */
#define GPS_EVERY      4
#define HEARTBEAT_MS   1000 /* repeat the armed state so modes know MSP is alive */
#define MIN_GPS_SATS   4
#define MAX_PAYLOAD    128

static const struct device *const uart = DEVICE_DT_GET(DT_ALIAS(msp_uart));

enum rx_state { RX_IDLE, RX_M, RX_DIR, RX_SIZE, RX_CMD, RX_PAYLOAD, RX_CRC };

static struct {
	enum rx_state state;
	bool error;
	uint8_t size, cmd, crc, len;
	uint8_t buf[MAX_PAYLOAD];
} rx;

/* Complete frame handed from the ISR to the work queue */
static struct {
	uint8_t cmd, len;
	uint8_t buf[MAX_PAYLOAD];
} frame;
static atomic_t frame_busy;

/* Bits of the boxes in the flight mode flags, from MSP_BOXIDS; -1: absent */
static int arm_bit = -1;
static int beeper_bit = -1;
static int failsafe_bit = -1;
static int state = -1;   /* last posted MSP_* bits, -1 unknown */
static int64_t moving_at = -1;
static int64_t last_post;
static uint32_t polls;
static bool running;

static void poll_fn(struct k_work *w);
static void frame_fn(struct k_work *w);
static K_WORK_DELAYABLE_DEFINE(poll_work, poll_fn);
static K_WORK_DEFINE(frame_work, frame_fn);

static void send(uint8_t cmd)
{
	const uint8_t msg[] = {'$', 'M', '<', 0, cmd, cmd}; /* crc = size ^ cmd */

	for (int i = 0; i < sizeof(msg); i++) {
		uart_poll_out(uart, msg[i]);
	}
}

/* Flight mode flag `bit` (index in MSP_BOXIDS): 32 bits at offset 6, more after offset 15 */
static bool mode_flag(const uint8_t *p, uint8_t len, int bit)
{
	int byte;

	if (bit < 0) {
		return false;
	}
	if (bit < 32) {
		return sys_get_le32(&p[6]) & BIT(bit);
	}
	byte = (bit - 32) / 8;
	if (len < 16 || byte >= (p[15] & 0x0f) || len < 16 + byte + 1) {
		return false;
	}
	return p[16 + byte] & BIT((bit - 32) % 8);
}

/*
 * Betaflight MSP_STATUS: cycleTime u16, i2cErrors u16, sensors u16, mode flags u32,
 * profile u8, load u16, gyro cycle u16, extra flag byte count u8 and bytes, arming
 * disable flag count u8, arming disable flags u32. INAV stops after the profile:
 * no arming flags, so no link-loss bit.
 */
static void handle_status(const uint8_t *p, uint8_t len)
{
	int64_t now = k_uptime_get();
	uint32_t disable = 0;
	int bits = 0;

	if (len < 10) {
		return;
	}
	if (len >= 16) {
		uint8_t at = 16 + (p[15] & 0x0f);

		if (len >= at + 5) {
			disable = sys_get_le32(&p[at + 1]);
		}
	}

	if (mode_flag(p, len, arm_bit)) {
		bits |= MSP_ARMED;
	}
	if (mode_flag(p, len, beeper_bit)) {
		bits |= MSP_BEEPER;
	}
	if (mode_flag(p, len, failsafe_bit) ||
	    (disable & (ARMING_DISABLED_FAILSAFE | ARMING_DISABLED_CRASH_DETECTED))) {
		bits |= MSP_FAILSAFE;
	}
	if (disable & ARMING_DISABLED_RX_FAILSAFE) {
		bits |= MSP_RXLOSS;
	}
	if (moving_at >= 0 && now - moving_at <= GPS_FRESH_MS) {
		bits |= MSP_MOVING;
	}

	if (bits != state || now - last_post >= HEARTBEAT_MS) {
		if (bits != state) {
			LOG_INF("FC%s%s%s%s%s", bits & MSP_ARMED ? " armed" : " disarmed",
				bits & MSP_BEEPER ? " beeper" : "",
				bits & MSP_FAILSAFE ? " failsafe" : "",
				bits & MSP_RXLOSS ? " rxloss" : "", bits & MSP_MOVING ? " moving" : "");
		}
		state = bits;
		last_post = now;
		modes_post(EV_MSP, bits);
	}
}

static void handle_gps(const uint8_t *p, uint8_t len)
{
	uint8_t fix, sats;

	if (len < 10) {
		return;
	}
	fix = p[0]; /* Betaflight: 0/2, INAV: 0 none, 1 2D, 2 3D */
	sats = p[1];
	if (fix >= 2 && sats >= MIN_GPS_SATS) {
		status_set_position((int32_t)sys_get_le32(&p[2]), (int32_t)sys_get_le32(&p[6]));
		/* lat, lon, alt u16, then ground speed u16 in cm/s */
		if (len >= 14 && sys_get_le16(&p[12]) > MOVING_CM_S) {
			moving_at = k_uptime_get();
		}
	}
}

static void handle_boxids(const uint8_t *p, uint8_t len)
{
	beeper_bit = -1;
	failsafe_bit = -1;
	for (int i = 0; i < len; i++) {
		switch (p[i]) {
		case BOXARM_ID:
			arm_bit = i;
			break;
		case BOXBEEPER_ID:
			beeper_bit = i;
			break;
		case BOXFAILSAFE_ID:
			failsafe_bit = i;
			break;
		}
	}
	if (arm_bit < 0) {
		LOG_WRN("ARM not in MSP_BOXIDS, assuming bit 0");
		arm_bit = 0;
	}
	LOG_INF("mode flag bits: ARM %d, BEEPER %d, FAILSAFE %d", arm_bit, beeper_bit,
		failsafe_bit);
}

static void frame_fn(struct k_work *w)
{
	switch (frame.cmd) {
	case MSP_BOXIDS:
		handle_boxids(frame.buf, frame.len);
		break;
	case MSP_STATUS:
		if (arm_bit >= 0) {
			handle_status(frame.buf, frame.len);
		}
		break;
	case MSP_RAW_GPS:
		handle_gps(frame.buf, frame.len);
		break;
	}
	atomic_clear(&frame_busy);
}

static void rx_byte(uint8_t c)
{
	switch (rx.state) {
	case RX_IDLE:
		rx.state = c == '$' ? RX_M : RX_IDLE;
		break;
	case RX_M:
		rx.state = c == 'M' ? RX_DIR : RX_IDLE;
		break;
	case RX_DIR:
		rx.error = c == '!';
		rx.state = (c == '>' || c == '!') ? RX_SIZE : RX_IDLE;
		break;
	case RX_SIZE:
		rx.size = c;
		rx.crc = c;
		rx.len = 0;
		rx.state = c <= MAX_PAYLOAD ? RX_CMD : RX_IDLE;
		break;
	case RX_CMD:
		rx.cmd = c;
		rx.crc ^= c;
		rx.state = rx.size ? RX_PAYLOAD : RX_CRC;
		break;
	case RX_PAYLOAD:
		rx.buf[rx.len++] = c;
		rx.crc ^= c;
		if (rx.len == rx.size) {
			rx.state = RX_CRC;
		}
		break;
	case RX_CRC:
		rx.state = RX_IDLE;
		if (c != rx.crc || rx.error) {
			break;
		}
		if (atomic_cas(&frame_busy, 0, 1)) {
			frame.cmd = rx.cmd;
			frame.len = rx.len;
			memcpy(frame.buf, rx.buf, rx.len);
			k_work_submit(&frame_work);
		}
		break;
	}
}

static void uart_isr(const struct device *dev, void *user_data)
{
	uint8_t buf[16];
	int n;

	while (uart_irq_update(dev) && uart_irq_rx_ready(dev)) {
		n = uart_fifo_read(dev, buf, sizeof(buf));
		for (int i = 0; i < n; i++) {
			rx_byte(buf[i]);
		}
	}
}

static void poll_fn(struct k_work *w)
{
	if (!running) {
		return;
	}
	if (arm_bit < 0) {
		send(MSP_BOXIDS);
	} else if (++polls % GPS_EVERY == 0) {
		send(MSP_RAW_GPS);
	} else {
		send(MSP_STATUS);
	}
	k_work_reschedule(&poll_work, K_MSEC(POLL_MS));
}

int msp_init(void)
{
	int err;

	if (!device_is_ready(uart)) {
		LOG_ERR("MSP UART not ready");
		return -ENODEV;
	}
	err = uart_irq_callback_user_data_set(uart, uart_isr, NULL);
	if (err) {
		return err;
	}
	pm_device_action_run(uart, PM_DEVICE_ACTION_SUSPEND);
	return 0;
}

void msp_start(void)
{
	if (running) {
		return;
	}
	running = true;
	rx.state = RX_IDLE;
	state = -1;
	moving_at = -1;
	arm_bit = -1; /* the FC may have been swapped or reconfigured */
	pm_device_action_run(uart, PM_DEVICE_ACTION_RESUME);
	uart_irq_rx_enable(uart);
	k_work_reschedule(&poll_work, K_NO_WAIT);
	LOG_INF("MSP polling started");
}

void msp_stop(void)
{
	if (!running) {
		return;
	}
	running = false;
	k_work_cancel_delayable(&poll_work);
	uart_irq_rx_disable(uart);
	pm_device_action_run(uart, PM_DEVICE_ACTION_SUSPEND);
	LOG_INF("MSP polling stopped");
}
