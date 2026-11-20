"""Build-local override for the pinned core; never edit an installed toolchain."""
import hashlib
from pathlib import Path
import shutil

PINNED = {
    "Wire_nRF52.cpp": "0fd5c77eedb088f9603847db55e9e5a1ec675566e89a09696c135170af795f87",
    "Wire.h": "aa235bb673bd218588807ad36caf40308bd9097d48a2d10a5d751f27bbf175cf",
}


def prepare(platform_path: Path, destination: Path) -> Path:
    source = platform_path / "libraries/Wire"
    for name, digest in PINNED.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Unexpected {name}; requires unmodified Adafruit nRF52 core 1.7.0")
    replacements = (Path(__file__).parent / "nrf_wire_master.inc").read_text()
    write_start = replacements.index("uint8_t TwoWire::endTransmission(")
    code = (source / "Wire_nRF52.cpp").read_text()
    start = code.index("uint8_t TwoWire::requestFrom(uint8_t address, size_t quantity, bool stopBit)")
    end = code.index("uint8_t TwoWire::requestFrom(uint8_t address, size_t quantity)\n", start)
    code = code[:start] + replacements[:write_start] + "\n" + code[end:]
    start = code.index("uint8_t TwoWire::endTransmission(bool stopBit)")
    end = code.index("uint8_t TwoWire::endTransmission()\n", start)
    code = code[:start] + replacements[write_start:] + "\n" + code[end:]
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "Wire_nRF52.cpp").write_text(code)
    (destination / "Wire.h").write_text(
        (source / "Wire.h").read_text() + "\n#define POSTUREPAL_WIRE_HW_BOUNDARIES 1\n"
    )
    shutil.copy2(source / "library.properties", destination / "library.properties")
    shutil.copy2(platform_path / "LICENSE", destination / "LICENSE")
    shutil.copy2(Path(__file__).parent / "licenses/LGPL-2.1.txt", destination / "COPYING.LIB")
    return destination
