/* SPDX-License-Identifier: MIT */
#include "dfu.h"
#include "status.h"

#include <zephyr/dfu/mcuboot.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/mgmt/mcumgr/mgmt/callbacks.h>
#include <zephyr/mgmt/mcumgr/mgmt/mgmt_defines.h>

LOG_MODULE_REGISTER(dfu, LOG_LEVEL_INF);

#define DFU_WINDOW_S  300 /* after the window opens */
#define DFU_EXTEND_S  60  /* after every accepted SMP command */

static atomic_t open;
static int64_t until_ms;

static void close_fn(struct k_work *w);
static K_WORK_DELAYABLE_DEFINE(close_work, close_fn);

static void extend(int s)
{
	int64_t t = k_uptime_get() + s * 1000LL;

	if (t > until_ms) {
		until_ms = t;
		k_work_reschedule(&close_work, K_MSEC(until_ms - k_uptime_get()));
	}
}

static void close_fn(struct k_work *w)
{
	atomic_clear(&open);
	status_update_flags(0, FLAG_DFU);
	LOG_INF("DFU window closed");
}

static enum mgmt_cb_return smp_cmd(uint32_t event, enum mgmt_cb_return prev_status, int32_t *rc,
				   uint16_t *group, bool *abort_more, void *data,
				   size_t data_size)
{
	if (!atomic_get(&open)) {
		*rc = MGMT_ERR_EACCESSDENIED;
		return MGMT_CB_ERROR_RC;
	}
	extend(DFU_EXTEND_S);
	return MGMT_CB_OK;
}

static struct mgmt_callback smp_cb = {
	.callback = smp_cmd,
	.event_id = MGMT_EVT_OP_CMD_RECV,
};

int dfu_init(void)
{
	/*
	 * MCUboot runs a new image once in test mode and reverts on the next reset
	 * unless it is confirmed. Getting here means Bluetooth and the modes came
	 * up, which is the self-test.
	 */
	if (!boot_is_img_confirmed()) {
		int err = boot_write_img_confirmed();

		LOG_INF("new image confirmed (%d)", err);
	}
	mgmt_callback_register(&smp_cb);
	return 0;
}

void dfu_open(void)
{
	atomic_set(&open, 1);
	until_ms = 0;
	extend(DFU_WINDOW_S);
	status_update_flags(FLAG_DFU, 0);
	LOG_INF("DFU window open for %d s", DFU_WINDOW_S);
}
