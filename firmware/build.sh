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
# MCUboot signing key: private, kept outside the repository (firmware/README.md,
# «Обновление прошивки»). Without it the SDK's public development key is used.
KEY=${CRICKET_MCUBOOT_KEY:-$HOME/.cricket/keys/mcuboot-ed25519.pem}
if [ -f "$KEY" ]; then
  CMAKE_ARGS="$CMAKE_ARGS '-DSB_CONFIG_BOOT_SIGNATURE_KEY_FILE=\"$KEY\"'"
else
  echo "build.sh: $KEY not found, signing with the SDK development key" >&2
fi
exec nrfutil sdk-manager toolchain launch --ncs-version "$NCS" -- sh -c \
  "cd /opt/nordic/ncs/$NCS && . zephyr/zephyr-env.sh && cd '$ROOT' && west build -b '$BOARD' --sysbuild firmware/app -d firmware/build $WEST_ARGS -- -DBOARD_ROOT='$ROOT/firmware' $CMAKE_ARGS"
