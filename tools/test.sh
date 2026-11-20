#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/posturepal-tests.XXXXXX")
trap 'rm -rf "$test_dir"' EXIT HUP INT TERM
sanitize_flags="-fsanitize=${POSTUREPAL_SANITIZERS:-address,undefined}"
${CXX:-c++} -std=c++11 -O2 -Wall -Wextra -Werror -pedantic "$sanitize_flags" \
  tests/test_nrf_wire.cpp -o "$test_dir/nrf-wire"
"$test_dir/nrf-wire"
${CXX:-c++} -std=c++11 -O2 -Wall -Wextra -Werror -pedantic "$sanitize_flags" \
  -I firmware/PosturePal tests/test_core.cpp firmware/PosturePal/vqf.cpp -o "$test_dir/core"
"$test_dir/core"
${CXX:-c++} -std=c++11 -O2 -Wall -Wextra -Werror -pedantic "$sanitize_flags" \
  -I tests/fakes -I firmware/PosturePal tests/test_firmware.cpp firmware/PosturePal/vqf.cpp -o "$test_dir/firmware"
"$test_dir/firmware"

# Exercise the M4's single-precision VQF path as well as the original double path.
${CXX:-c++} -std=c++11 -O2 -Wall -Wextra -Werror -pedantic "$sanitize_flags" \
  -DVQF_SINGLE_PRECISION -I firmware/PosturePal tests/test_core.cpp firmware/PosturePal/vqf.cpp -o "$test_dir/core-float"
"$test_dir/core-float"
${CXX:-c++} -std=c++11 -O2 -Wall -Wextra -Werror -pedantic "$sanitize_flags" \
  -DVQF_SINGLE_PRECISION -I tests/fakes -I firmware/PosturePal tests/test_firmware.cpp firmware/PosturePal/vqf.cpp -o "$test_dir/firmware-float"
"$test_dir/firmware-float"

# BLE framing/queue behavior; radio timing remains a physical bench check.
${CXX:-c++} -std=c++11 -O2 -Wall -Wextra -Werror -pedantic "$sanitize_flags" \
  -DARDUINO_NRF52840_FEATHER -I tests/fakes -I firmware/PosturePal tests/test_ble.cpp -o "$test_dir/ble"
"$test_dir/ble"

# Exercise the nRF sketch with BLE compiled in and its single-precision VQF build.
${CXX:-c++} -std=c++11 -O2 -Wall -Wextra -Werror -pedantic "$sanitize_flags" \
  -DARDUINO_NRF52840_FEATHER -DVQF_SINGLE_PRECISION \
  -I tests/fakes -I firmware/PosturePal tests/test_firmware.cpp firmware/PosturePal/vqf.cpp -o "$test_dir/firmware-nrf-float"
"$test_dir/firmware-nrf-float"
