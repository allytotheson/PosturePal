#!/usr/bin/env python3
"""Check pinned dependencies and build; never uploads or changes installed packages."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CLI = os.environ.get("ARDUINO_CLI") or shutil.which("arduino-cli")
MAC_CLI = "/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"
if not CLI and Path(MAC_CLI).is_file():
    CLI = MAC_CLI
if not CLI:
    sys.exit("Install Arduino CLI or set ARDUINO_CLI; see docs/SETUP.md")

def query(*args):
    return json.loads(subprocess.check_output([CLI, *args, "--format", "json"], text=True))

platforms = query("core", "list")["platforms"]
if not any(p["id"] == "adafruit:nrf52" and p.get("installed_version") == "1.7.0" for p in platforms):
    sys.exit("Requires installed adafruit:nrf52@1.7.0; see docs/SETUP.md")
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
build_dir = Path(os.environ.get("POSTUREPAL_BUILD_DIR", ROOT / "build/feather52840")).resolve()
command = [CLI, "compile", "--fqbn", "adafruit:nrf52:feather52840", "--warnings", "all",
           "--build-path", str(build_dir), "--build-property", "compiler.optimization_flag=-O2",
           *library_args, str(ROOT / "firmware/PosturePal")]
print("Pinned dependencies verified. Building with -O2 (IEEE NaN behavior).", flush=True)
subprocess.run(command, check=True)
