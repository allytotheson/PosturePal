#!/usr/bin/env python3
"""Check pinned dependencies and build; upload only with --upload --port."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--board", choices=("feather-m4", "nrf52840"), default="feather-m4")
parser.add_argument("--upload", action="store_true", help="Upload after a successful build")
parser.add_argument("--port", help="Serial device to upload to, e.g. /dev/cu.usbmodem123")
args = parser.parse_args()
if args.upload and not args.port:
    parser.error("--upload requires --port (find it in Arduino IDE Tools > Port)")
if args.port and not args.upload:
    parser.error("--port requires --upload")
if args.board == "feather-m4":
    core, core_version = "adafruit:samd", "1.7.17"
    fqbn = "adafruit:samd:adafruit_feather_m4:opt=fast,usbstack=tinyusb"
    output_name = "feather_m4"
    # SAMD uses newlib-nano: explicitly retain floating-point vsnprintf support.
    build_args = ["--build-property", "compiler.c.elf.extra_flags=-Wl,-u,_printf_float",
                  "--build-property", "compiler.cpp.extra_flags=-DVQF_SINGLE_PRECISION"]
else:
    core, core_version = "adafruit:nrf52", "1.7.0"
    fqbn, output_name = "adafruit:nrf52:feather52840", "feather52840"
    # Cortex-M4F hardware supports float, not the VQF double default.
    # Keep the sample/fault limits intact; verify vqf_bits=32 and timing on hardware.
    build_args = ["--build-property", "compiler.optimization_flag=-O2",
                  "--build-property", "compiler.cpp.extra_flags=-DVQF_SINGLE_PRECISION -DPOSTUREPAL_REQUIRE_HW_WIRE"]
CLI = os.environ.get("ARDUINO_CLI") or shutil.which("arduino-cli")
MAC_CLI = "/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"
if not CLI and Path(MAC_CLI).is_file():
    CLI = MAC_CLI
if not CLI:
    sys.exit("Install Arduino CLI or set ARDUINO_CLI; see docs/SETUP.md")

def query(*args):
    return json.loads(subprocess.check_output([CLI, *args, "--format", "json"], text=True))

platforms = query("core", "list")["platforms"]
if not any(p["id"] == core and p.get("installed_version") == core_version for p in platforms):
    sys.exit(f"Requires installed {core}@{core_version}; see docs/SETUP.md and docs/FEATHER_M4.md")
libraries = query("lib", "list")["installed_libraries"]
pinned = {"Adafruit LSM6DS": "4.7.4", "Adafruit DRV2605 Library": "1.2.4",
          "Adafruit BusIO": "1.17.4", "Adafruit Unified Sensor": "1.1.15"}
library_args = []
for name, version in pinned.items():
    found = [entry["library"] for entry in libraries if entry["library"]["name"] == name]
    if len(found) != 1 or found[0]["version"] != version:
        sys.exit(f"Requires one installed {name}@{version}; remove conflicting versions. See docs/SETUP.md")
    library_args.extend(["--library", found[0]["install_dir"]])
for name, checksum in {
    "vqf.hpp": "ef15c074bce16adb76e7f191970ea589bc6d7ce01027130e5233041c0e11eb24",
    "vqf.cpp": "fb035248ebeccc16897476c7afca5e912f3ad77f0faebd16ff4d5f94b44c614b",
}.items():
    if hashlib.sha256((ROOT / "firmware/PosturePal" / name).read_bytes()).hexdigest() != checksum:
        sys.exit(f"Vendored {name} differs from official VQF 2.1.2")
build_dir = Path(os.environ.get("POSTUREPAL_BUILD_DIR", ROOT / "build" / output_name)).resolve()
if args.board == "nrf52840":
    from nrf_wire import prepare
    details = query("board", "details", "--fqbn", fqbn)
    properties = dict(p.split("=", 1) for p in details["build_properties"])
    platform_path = Path(properties["runtime.platform.path"])
    try:
        wire = prepare(platform_path, build_dir.parent / (build_dir.name + "-Wire"))
    except (OSError, ValueError) as error:
        sys.exit(f"Cannot prepare nRF Wire override: {error}")
    library_args.extend(["--library", str(wire)])
command = [CLI, "compile", "--fqbn", fqbn, "--warnings", "all",
           "--build-path", str(build_dir), *build_args,
           *library_args, str(ROOT / "firmware/PosturePal")]
print(f"Pinned dependencies verified. Building {args.board} with -O2 (IEEE NaN behavior).", flush=True)
subprocess.run(command, check=True)

if args.upload:
    print(f"Uploading {args.board} to {args.port}...", flush=True)
    subprocess.run([CLI, "upload", "--fqbn", fqbn, "--port", args.port,
                    "--input-dir", str(build_dir), str(ROOT / "firmware/PosturePal")], check=True)
    print("Upload complete. Open Serial Monitor at 115200 baud; send status.", flush=True)
else:
    print("BUILD ONLY: firmware was NOT flashed. To flash, rerun with --upload --port YOUR_PORT.", flush=True)
