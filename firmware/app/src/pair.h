/* SPDX-License-Identifier: MIT */
/*
 * Bonding with the owner's phone. New pairing is accepted only inside a
 * pairing window opened on the beacon (button hold 3 s, or the DFU hold at
 * power-up). Bonds are stored in the settings partition and survive resets and
 * firmware updates. Control commands and SMP need an encrypted (bonded) link.
 */
#pragma once

#include <zephyr/bluetooth/addr.h>

int pair_init(void);
void pair_open(void);
/* Remove every bond except this peer (owner lost or replaced a phone). */
void pair_forget_others(const bt_addr_le_t *keep);
