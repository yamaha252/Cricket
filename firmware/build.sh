#!/bin/sh
# Build the Cricket tag firmware inside the nRF Connect SDK toolchain (D-32).
# Usage: firmware/build.sh [board] [west build args...] [-- cmake args...]
# Boards: nrf54l15dk/nrf54l15/cpuapp (default), cricket_tag/nrf54l15/cpuapp (firmware/boards).
# Example: firmware/build.sh nrf54l15dk/nrf54l15/cpuapp -p always -- -DEXTRA_DTC_OVERLAY_FILE=msp-dk.overlay
set -e
NCS=v3.4.2
BOARD=${1:-nrf54l15dk/nrf54l15/cpuapp}
[ $# -gt 0 ] && shift
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WEST_ARGS=""
while [ $# -gt 0 ] && [ "$1" != "--" ]; do
  WEST_ARGS="$WEST_ARGS '$1'"
  shift
done
[ "$1" = "--" ] && shift
CMAKE_ARGS=""
for a in "$@"; do
  CMAKE_ARGS="$CMAKE_ARGS '$a'"
done
exec nrfutil sdk-manager toolchain launch --ncs-version "$NCS" -- sh -c \
  "cd /opt/nordic/ncs/$NCS && . zephyr/zephyr-env.sh && cd '$ROOT' && west build -b '$BOARD' --sysbuild firmware/app -d firmware/build $WEST_ARGS -- -DBOARD_ROOT='$ROOT/firmware' $CMAKE_ARGS"
