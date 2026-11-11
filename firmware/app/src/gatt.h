/* SPDX-License-Identifier: MIT */
/* Cricket GATT service: status (read/notify) and control (write); docs/protocol.md. */
#pragma once

#define CRICKET_CMD_FIND    0x01
#define CRICKET_CMD_SILENCE 0x02
#define CRICKET_CMD_DFU     0x03
#define CRICKET_CMD_FORGET  0x04

void gatt_notify_status(void);
