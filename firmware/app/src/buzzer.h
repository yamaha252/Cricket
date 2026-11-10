/* SPDX-License-Identifier: MIT */
/* Buzzer (PAM8904E driven by PWM) and flash LED, played as patterns. */
#pragma once

#include <stdbool.h>
#include <stdint.h>

enum buzz_pattern {
	BUZZ_OFF,
	BUZZ_TEST,   /* one short beep and flash: button press, self-test */
	BUZZ_ACK,    /* two short beeps: command accepted */
	BUZZ_CHIRP,  /* quiet short chirp: ESCALATE warning */
	BUZZ_ALARM,  /* loud burst: ALARM */
	BUZZ_BEACON, /* single loud beep: BEACON */
	BUZZ_FIND,   /* repeat beeps for the given time: app command */
	BUZZ_BYE,    /* falling double beep before SHIP */
};

int buzzer_init(void);
/* duration_s is used by BUZZ_FIND only. A new pattern replaces the one playing. */
void buzzer_play(enum buzz_pattern pattern, uint8_t duration_s);
bool buzzer_active(void);
