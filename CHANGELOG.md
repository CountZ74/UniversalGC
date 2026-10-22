# Changelog

🇬🇧 English · German summaries are in the [release notes](https://github.com/CountZ74/UniversalGC/releases).

Hardware status: **✓ tested** = confirmed on a real device, **○ untested** = covered by the
automated tests and the simulator, but not yet run on hardware.

## 1.1

### New
- **Rotary selector** (`selectors`) – fixed positions on *one* analog pin, one button per
  position, exactly one pressed: AS5600 behind a detent knob (spacing in degrees,
  "current position as position 1" in the web interface, full circle wraps around) or a
  rotary switch with a resistor ladder. ○
- **AS5600 as encoder** – encoder type `as5600`: an AS5600 behind a (3D-printed) detent
  knob on one analog pin; every detent pulses "right"/"left", endless rotation,
  hysteresis between detents. ○
- **Pot filtering** – per pot axis `smooth` (moving average, default 3) and `hyst`
  (hysteresis, default 0.5 %): noisy pots stay still, end stops are still reached
  exactly. ○
- **Center position** for pot axes (`center`) – 50 % at the calibrated center, both
  halves scaled separately, deadzone around the center. ○
- **"Check" warns about lost axes** – the web interface knows how Linux (`hid-input.c`)
  and Windows (DirectInput) map axes and warns when an axis is dropped or two collide
  (e.g. Sim brake and Rz on Windows). Sim clutch, toe brake, aileron, elevator and
  collective are marked as unsupported by both. ✓ (Sim clutch missing on Linux and Windows,
  Sim brake + Rz collision on Windows confirmed on hardware)
- **Option: USB reports without report ID** (`options.report_id = false`) – byte-identical
  to the old firmwares, for programs that misread the report ID. ○
- **Installer: one list for all boards** – visible drives and boards reachable only over
  the serial console appear together; previously one visible drive hid all other boards. ○
- **English README** (`README.md`), German version as `README.de.md`, plus a
  troubleshooting table and a "How this was built" section.

### Fixed
- **Device name on Windows** – the HID interface now carries the USB product name instead
  of "CircuitPython HID"; see the README for clearing Windows' name cache. ✓ (USB)
- **Bluetooth device ID** – BLE now reports the same VID/PID as USB instead of 0000/0000
  ("0-axis 16-button device" on Windows). ○
- **USB hangs** – when the PC does not poll the device (Linux, no program has it open),
  `send_report` blocked for up to 2 s per report; with noisy pots the whole firmware
  stalled (web interface: connection reset, inputs stale). Slow reports now pause USB for
  5 s and resend the current state afterwards. ○
- **PC scripts on Windows** – text files are always read as UTF-8; umlauts in
  `device.json`, templates or old `settings.py` were garbled under Windows' default
  encoding. ○

### Known issues
- Stormworks (under Proton) shows phantom buttons 33/34/37 and a stuck UI cursor with
  the button box although `jstest` shows nothing pressed. Cause unknown; the report-ID
  option above is untested for this case.

## 1.0

First release. Pedals (Pico W), button box (Pico 2 W) and steering wheel (ESP32-S3,
USB and Bluetooth) tested on hardware.
