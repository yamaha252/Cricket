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

#define BOXARM_ID      0   /* permanent box id of ARM in Betaflight and INAV */
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

static int arm_bit = -1; /* bit of ARM in the flight mode flags, from MSP_BOXIDS */
static int armed = -1;   /* -1 unknown */
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

static void handle_status(const uint8_t *p, uint8_t len)
{
	uint32_t flags;
	int now_armed;
	int64_t now = k_uptime_get();

	if (len < 10) {
		return;
	}
	flags = sys_get_le32(&p[6]); /* cycleTime u16, i2cErrors u16, sensors u16, flags u32 */
	now_armed = (flags & BIT(arm_bit)) != 0;

	if (now_armed != armed || now - last_post >= HEARTBEAT_MS) {
		if (now_armed != armed) {
			LOG_INF("FC %s", now_armed ? "armed" : "disarmed");
		}
		armed = now_armed;
		last_post = now;
		modes_post(armed ? EV_ARMED : EV_DISARMED, 0);
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
	}
}

static void handle_boxids(const uint8_t *p, uint8_t len)
{
	for (int i = 0; i < len; i++) {
		if (p[i] == BOXARM_ID) {
			arm_bit = i;
			LOG_INF("ARM is flight mode bit %d", i);
			return;
		}
	}
	LOG_WRN("ARM not in MSP_BOXIDS, assuming bit 0");
	arm_bit = 0;
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
	armed = -1;
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
