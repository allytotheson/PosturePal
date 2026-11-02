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
