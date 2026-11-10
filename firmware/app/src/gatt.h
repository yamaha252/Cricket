/* SPDX-License-Identifier: MIT */
/* Cricket GATT service: status (read/notify) and control (write); docs/protocol.md. */
#pragma once

#define CRICKET_CMD_FIND    0x01
#define CRICKET_CMD_SILENCE 0x02

void gatt_notify_status(void);
