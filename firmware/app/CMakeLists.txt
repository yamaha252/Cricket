# SPDX-License-Identifier: MIT

cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(cricket_tag)

target_sources(app PRIVATE
  src/main.c
  src/status.c
  src/adv.c
  src/gatt.c
  src/buzzer.c
  src/battery.c
  src/inputs.c
  src/modes.c
  src/dfu.c
  src/pair.c
  src/wdog.c
)
target_sources_ifdef(CONFIG_CRICKET_MSP app PRIVATE src/msp.c)
target_sources_ifdef(CONFIG_CRICKET_IMPACT app PRIVATE src/impact.c)
