#!/bin/sh
# Build the Cricket tag firmware inside the nRF Connect SDK toolchain (D-32).
# Usage: firmware/build.sh [board] [extra west build args...]
set -e
NCS=v3.4.2
BOARD=${1:-nrf54l15dk/nrf54l15/cpuapp}
[ $# -gt 0 ] && shift
ROOT=$(cd "$(dirname "$0")/.." && pwd)
exec nrfutil sdk-manager toolchain launch --ncs-version "$NCS" -- sh -c \
  "cd /opt/nordic/ncs/$NCS && . zephyr/zephyr-env.sh && cd '$ROOT' && west build -b '$BOARD' --sysbuild firmware/app -d firmware/build $*"
