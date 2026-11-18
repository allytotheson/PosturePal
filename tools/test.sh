#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/posturepal-tests.XXXXXX")
trap 'rm -rf "$test_dir"' EXIT HUP INT TERM
${CXX:-c++} -std=c++11 -O2 -Wall -Wextra -Werror -pedantic -fsanitize=address,undefined \
  -I firmware/PosturePal tests/test_core.cpp firmware/PosturePal/vqf.cpp -o "$test_dir/core"
"$test_dir/core"
${CXX:-c++} -std=c++11 -O2 -Wall -Wextra -Werror -pedantic -fsanitize=address,undefined \
  -I tests/fakes -I firmware/PosturePal tests/test_firmware.cpp firmware/PosturePal/vqf.cpp -o "$test_dir/firmware"
"$test_dir/firmware"

# Exercise the M4's single-precision VQF path as well as the original double path.
${CXX:-c++} -std=c++11 -O2 -Wall -Wextra -Werror -pedantic -fsanitize=address,undefined \
  -DVQF_SINGLE_PRECISION -I firmware/PosturePal tests/test_core.cpp firmware/PosturePal/vqf.cpp -o "$test_dir/core-float"
"$test_dir/core-float"
${CXX:-c++} -std=c++11 -O2 -Wall -Wextra -Werror -pedantic -fsanitize=address,undefined \
  -DVQF_SINGLE_PRECISION -I tests/fakes -I firmware/PosturePal tests/test_firmware.cpp firmware/PosturePal/vqf.cpp -o "$test_dir/firmware-float"
"$test_dir/firmware-float"

# BLE framing/queue behavior; radio timing remains a physical bench check.
${CXX:-c++} -std=c++11 -O2 -Wall -Wextra -Werror -pedantic -fsanitize=address,undefined \
  -DARDUINO_NRF52840_FEATHER -I tests/fakes -I firmware/PosturePal tests/test_ble.cpp -o "$test_dir/ble"
"$test_dir/ble"
