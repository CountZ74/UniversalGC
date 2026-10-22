# UniversalGC

🇬🇧 English · 🇩🇪 [Deutsch](README.de.md)

**A universal game controller firmware for CircuitPython, in the spirit of FreeJoy.**
Pedals, button boxes, steering wheels, flight sim panels, arcade sticks – what is wired to
which pin lives in `device.json` and is configured **in the browser**, over a Wi-Fi
access point the device opens itself. No compiler, no flashing tool, no PC software.

- Runs on **Raspberry Pi Pico W / Pico 2 W** and **ESP32-S3** (with Bluetooth LE)
- **Pin finder:** press your buttons, turn your encoders – the device tells you what is
  connected where
- Buttons, matrices, shift registers, encoders, pots, Hall sensors, AS5600, load cells
- Logic buttons and LEDs driven by **SimHub telemetry**, WS2812 rev lights, rumble motors
- Safety net: every configuration is checked before saving, and if a new one fails to
  start twice, the previous one comes back

> **Language note:** the web interface, the installer messages and the code comments are
> currently in **German**. The configuration keys in `device.json` are English. Help with
> translations is welcome.

UniversalGC grew out of two single-purpose firmwares it replaces:
[sim-pedale](https://github.com/CountZ74/sim-pedale) (pedals v9.9) and a button box v2.1.
Everything that was measured and tuned on real hardware there – wrap-around calibration,
load cell via PIO, slow-decay rumble, logic buttons – carries over. Comments such as
"Pedale v9.4" refer to that version history.

## Features

| Feature | Details |
|---|---|
| Buttons | wired to GND; modes *normal*, *pulse* (toggle switch → one press on every flip) or *toggle* (push button acts as a switch); normally-closed contacts supported |
| Button matrix | any number of rows × columns, with diodes (either direction) |
| Shift registers | 74HC165 chains, 8 inputs each – many buttons on few pins |
| Encoders | one press per detent, left/right; fast turns are buffered so the game sees every step; or used as an axis |
| AS5600 encoder | a 3D-printed detent knob over an AS5600 instead of a mechanical encoder – **one analog pin**, contactless, no bounce |
| Rotary selector | fixed positions on **one analog pin** (AS5600 + detent knob, or a rotary switch with a resistor ladder): one button per position, exactly one pressed |
| Axes (16 bit) | pot/Hall, AS5600 (wrap-around), HX711 load cell (PIO on the Pico), encoder |
| Pot filtering | smoothing and hysteresis so noisy pots stay still; optional **center position** with deadzone around the middle |
| HID axes | X, Y, Z, Rx, Ry, Rz, Slider, Dial – or Simulation Controls (accelerator, brake, steering …, see below) |
| Response curves | drawn per axis in the browser |
| Logic buttons | `AND(b9,b10,NOT(motor))`, `GT(rpm,7000)`, `GT(a0,90)` … with SimHub telemetry |
| LEDs | on/blink driven by logic expressions |
| WS2812 | rev light bar with shift flash, rules for pit limiter, flags etc. |
| Rumble | DRV8871 with dead-man timeout and emergency stop, effects from SimHub ShakeIt |
| Bluetooth LE | ESP32-S3 only (see below) |
| Config access | dedicated config button **or** a button combination held for a few seconds |
| Safety net | pins are validated before saving, the old configuration is kept as a backup and restored if the new one fails to start twice |

### Planned

For general-purpose controllers (see Issues): hat switch / POV, shift layer, keyboard/mouse
output.

## Which board?

| Board | USB joystick | Bluetooth | Typical use |
|---|---|---|---|
| Raspberry Pi Pico W / Pico 2 W | yes | no (no BLE under CircuitPython) | pedals, button box |
| **ESP32-S3** (e.g. DevKitC-1, YD-ESP32-S3, QT Py ESP32-S3) | yes | **yes** | steering wheel |
| plain ESP32, ESP32-C3 | no | yes | not suitable (no native USB) |

Notes for the ESP32-S3:
- The circuitpython.org web installer asks for your home Wi-Fi and writes it to
  `settings.toml`. **Comment out `CIRCUITPY_WIFI_SSID`, `CIRCUITPY_WIFI_PASSWORD` and
  `CIRCUITPY_WEB_API_PASSWORD`** – otherwise CircuitPython connects by itself, its web
  editor takes port 80 and the UniversalGC access point does not start.
- Analog inputs are only reliable on **GPIO1–10**. GPIO11–20 (ADC2) do not measure while
  Wi-Fi is on – the firmware warns about it.
- GPIO19/20 are USB, GPIO26–37 are usually flash/PSRAM – both are blocked.
- **Do not use GPIO0 as config button:** held while plugging in, it starts the ROM
  bootloader.
- No PIO – a load cell is read by bit-banging (slower).
- Too few USB endpoints for a second serial port: the ESP32-S3 has 4 IN endpoints,
  console + data port + joystick would need 5 (CircuitPython would drop into safe mode).
  Telemetry therefore uses the **single** serial port (the console) – select that port
  in SimHub.
- Bluetooth latency depends on the connection interval chosen by the PC (Linux: often
  30–50 ms). To shorten it on Linux until the next reboot, then reconnect:
  `sudo sh -c 'echo 6 > /sys/kernel/debug/bluetooth/hci0/conn_min_interval'`
  (6 × 1.25 ms = 7.5 ms). The device does not request it itself – CircuitPython hangs if
  the host never answers that request.
- On battery or power bank (no USB host), reports go out over Bluetooth only.

## Installation

1. Install CircuitPython 10.x on the board (https://circuitpython.org/downloads).
2. Download the **release package** (`UniversalGC-<version>-cp10.zip` – `cp10` means
   CircuitPython 10.x; precompiled `.mpy` files only work with that major version) from
   the Releases page and unzip it. It contains precompiled modules – which saves noticeable memory on
   the Pico W – and the required libraries.
3. Install:
   ```bash
   python3 installieren.py lenkrad      # with a template as device.json (pedale, buttonbox, lenkrad)
   python3 installieren.py              # update only, configuration is kept
   python3 installieren.py --liste      # list templates
   ```
   On Windows use `py` instead of `python3`.

   The script finds `CIRCUITPY` by itself (Linux, macOS, Windows), copies in the right
   order (`boot.py` last), removes stale files, fetches missing libraries from the
   official Adafruit bundle matching your CircuitPython version (cached in
   `~/.cache/universalgc`; offline: [circup](https://github.com/adafruit/circup) or
   `--bundle ZIP`) and flushes everything to the drive before it reports success. The
   same script works straight from the source repository.
4. **Eject** the drive, unplug, plug back in.

**Updating a device in normal operation** (drive hidden): just run `python3 installieren.py`.
With `pyserial` installed, the script finds boards on their serial ports, restarts them
with the drive visible, waits for `CIRCUITPY` and installs. Close Thonny first – it
blocks the port. With several boards connected you get one list containing both visible
drives and boards reachable only over the console; `--seriell` lists only the latter.
Without `pyserial`, or with an old firmware: enable maintenance mode by hand (hold the
config button while plugging in, or web interface → "Neustart mit Laufwerk").

| System | pyserial | circup |
|---|---|---|
| Arch / Manjaro | `sudo pacman -S python-pyserial` | `pipx install circup` (rarely needed) |
| Debian / Ubuntu | `sudo apt install python3-serial` | `pipx install circup` |
| Windows / macOS | `py -m pip install pyserial` | `pip install circup` |

On Linux your user needs access to serial ports: group `uucp` (Arch) or `dialout`
(Debian/Ubuntu), e.g. `sudo usermod -aG uucp $USER`, then log in again.

Without Python: copy the package contents to `CIRCUITPY`, `boot.py` last, eject. Delete
old firmware `.py` modules in the root first – they would shadow the new `.mpy` files in
`lib/`.

If a required file is missing at startup, `boot.py` keeps the drive visible
(`boot_out.txt` says what is missing). Without `device.json`, or with neither config button
nor button combination, `CIRCUITPY` also stays visible (setup mode). The device then shows
up with 8 empty buttons, starts the access point by itself (Wi-Fi `UniversalGC-Setup`,
password `universalgc`) and offers the templates in the browser.

### Building the package yourself

```bash
python3 werkzeuge/paket.py --mpy-cross PATH/TO/mpy-cross [--bundle adafruit-…-10.x-mpy-….zip]
```
`mpy-cross` must come from **CircuitPython** (not MicroPython) and match the major
version on the board; build it in the CircuitPython source tree with `make -C mpy-cross`.
GitHub Actions builds the package on every push (`.github/workflows/paket.yml`) and
attaches it to a release for every `v…` tag.

### Libraries (`lib/`)

Included in the release package; `installieren.py` copies only what the configuration
needs. By hand, from the Adafruit bundle matching your CircuitPython version:

| For | File/folder |
|---|---|
| load cell via PIO (Pico) | `adafruit_pioasm.mpy` |
| load cell via bit-banging (ESP32-S3) | `adafruit_hx711/` |
| WS2812 | `neopixel.mpy` |
| Bluetooth (ESP32-S3) | `adafruit_ble/` |

Buttons, matrix, shift registers and encoders need nothing – `keypad` and `rotaryio` are
built in.

**Memory:** with Wi-Fi, many axes and WS2812 the Pico W gets tight – use the release
package with precompiled modules. The status page shows free memory.

## Usage

- **Short press on the config button:** access point on/off. Connect your phone, open
  `http://192.168.4.1`. The button also acts as emergency stop for rumble motors.
  Default access point names and passwords are in the templates (e.g. `Pico-Pedale` /
  `pedale123`).
- **Button combination instead of a config button:** in *Belegung* (configuration) enter
  button numbers under *Tastenkombination*, e.g. `1, 2` – in `device.json`:
  `"config_combo": {"buttons": [1, 2], "hold": 3}`. Holding them together for `hold`
  seconds toggles the access point. Buttons, matrix and shift register inputs are
  allowed; they are also sent to the PC, so pick a combination that does nothing harmful
  in-game. Held while plugging in, it opens maintenance mode (directly wired buttons
  only).
- **Maintenance mode:** hold the config button while plugging in → `CIRCUITPY` stays
  visible as a drive; the device cannot save in this mode.
- **Saving while the drive is visible:** if `CIRCUITPY` currently belongs to the PC
  (maintenance, setup, or files were just copied without a real restart), the new
  configuration waits in NVM. The device restarts, enumerates with it right away and
  writes it as `device.json`. The new configuration needs a config button or a button
  combination for that.
- **Changing the configuration:** tab *Belegung* → *Prüfen* (check) → *Speichern &
  Neustart* (save & restart). The PC only reads the HID layout when the device is plugged
  in, hence the restart. New button numbers or axes have to be re-bound once in-game.
- **Pot axes:** smoothing (`smooth`, default 3) and hysteresis (`hyst`, default 0.5 %) keep
  noisy pots still. With **center position** (`center`) 50 % sits in the middle and the
  deadzone is around the center – for detented knobs, trim or Hall sticks. Calibrate: set
  center, then turn to both end stops.
- **AS5600 as encoder:** instead of a mechanical encoder (pins A and B) use an AS5600
  behind a knob with detents, e.g. 3D-printed: one analog pin (`OUT`), contactless, no
  bounce. In *Belegung → Encoder* choose type "AS5600 + Rastenknopf" and enter the number
  of detents per revolution. Every detent sends a pulse on "right" or "left". The knob
  must rest in a detent at power-up.
- **Rotary selector (Stufenschalter):** fixed positions on *one* analog pin – one button
  per position, exactly one pressed. Either an AS5600 behind a detent knob (position
  spacing in degrees; capture position 1 with "Aktuelle Stellung als Stellung 1"; if the
  positions fill the full circle it wraps from the last to the first), or a standard
  rotary switch with a resistor ladder (equal resistors between the contacts, ends to
  GND and 3.3 V).
- **Fixed button numbers:** every source (buttons, matrix, shift register, encoder,
  logic) can pin its first number with `btn`, so in-game bindings survive when you add
  hardware later.

### Pin finder

In tab *Belegung*, the **pin finder** figures out what is connected where:

1. **"Taster & Encoder suchen"** (find buttons & encoders) – press every button once, turn
   every encoder a few detents, flip toggle switches. Detected: buttons, held switches
   (suggested as "pulse"), encoders (two pins switching alternately).
2. **"Achsen suchen"** (find axes) – move pots and Hall paddles through their full range.
   During the first second the finder learns the noise floor, then it reports pins that
   move clearly.
3. For every hit click **"übernehmen"** (apply) – or "als Konfig-Taster" for a button –
   adjust names, *Prüfen*, *Speichern & Neustart*.

Only free pins are watched, and only as inputs – the finder never drives outputs.
Strapping pins (ESP32-S3: GPIO0, 3, 45, 46), USB and flash pins are skipped. LEDs, WS2812,
rumble motors, load cells and button matrices cannot be detected and are entered by hand.
The finder stops by itself after 5 minutes.

### Maintenance mode without a button

Thonny uploads to CircuitPython via the `CIRCUITPY` drive, which is hidden in normal
operation. Without pressing the config button:

- web interface, tab *Status*: **"Neustart mit Laufwerk CIRCUITPY"**, or
- in the Thonny shell (Ctrl+C first):
  ```python
  import merker; merker.wartung()
  ```

The device restarts once with the drive visible. The next plug-in is back to normal.

### Rollback

On saving, the old configuration is kept as `device.bak.json` and `cfg_pending` is
created. Once the device has run cleanly for 15 seconds, the marker is removed. If the
start fails twice in a row, `boot.py` restores the old configuration. The reason is in
`fehler.txt` or `boot_out.txt`.

## Simulation Controls or Rx/Ry/Rz?

Every axis can report as a regular joystick axis (X … Rz, Slider) or as a *Simulation
Control* (`"usage": "brake"` etc., "Sim: Bremse" in the browser). The latter describes
pedals and wheels more accurately, but operating systems only support some of them and
map them onto regular axes. The templates therefore use Rx/Ry/Rz, which is proven to work.

What the systems make of them (two axes on the same target: the second one is dropped):

| Axis | Linux (`hid-input.c`) | Windows (DirectInput, as documented by MAME) |
|---|---|---|
| X, Y, Z, Rx, Ry, Rz | same name | same name |
| Slider / Dial | ABS_THROTTLE / ABS_RUDDER | Slider (two available) |
| Sim: accelerator | ABS_GAS | **Y** |
| Sim: brake | ABS_BRAKE | **Rz** |
| Sim: steering | ABS_WHEEL | **X** |
| Sim: throttle | ABS_THROTTLE | Slider |
| Sim: rudder | ABS_RUDDER | **Rz** |
| Sim: clutch, toe brake, aileron/elevator, collective | – missing | – missing (confirmed on hardware for the clutch) |

So Sim accelerator and Sim brake collide with Y or Rz on Windows. *Prüfen* in the web
interface warns about such cases. Report a clutch as **Slider**.

## Templates

| File | Device | Board | USB PID |
|---|---|---|---|
| `pedale.json` | 3 pedals: AS5600 throttle/clutch, load cell brake, 2 rumble motors – like pedals v9.9 | Pico W | 0x4712 |
| `buttonbox.json` | 11 buttons/switches, 3 pots, 16 logic buttons from 23, starter LED – button numbers like button box v2.1 | Pico 2 W | 0x4711 |
| `lenkrad.json` | 2 shift paddles, 4×4 matrix, 2 encoders, 2 clutch paddles (Hall), 10 WS2812, Bluetooth | ESP32-S3 (DevKitC-1, YD-ESP32-S3 …) | 0x4713 |

The steering wheel pins are a suggestion – adapt them to your board when wiring.

**Pin names:** the same chip pin is called `IO21` (Espressif DevKitC-1), `GPIO21`
(YD-ESP32-S3 and many others) or `GP21` (Pico). If a board does not know a name, the
firmware tries the other spellings – so the templates fit any board. To see a board's
pin names, run `import board; print(dir(board))` in the Thonny shell.

### Device name on Windows

The device reports its USB product name (*Belegung → USB-Produktname*) as the name of
its HID interface, which is what Windows shows under *Set up USB game controllers*.
Windows caches that name per VID/PID the first time it sees a device. If an old name
("CircuitPython HID") sticks, delete the cached entries in PowerShell (as administrator)
and replug:

```powershell
$k = "HKCU:\System\CurrentControlSet\Control\MediaProperties\PrivateProperties\Joystick\OEM",
     "HKLM:\SYSTEM\CurrentControlSet\Control\MediaProperties\PrivateProperties\Joystick\OEM"
Get-ChildItem $k -ErrorAction SilentlyContinue | Where-Object {
    (Get-ItemProperty $_.PSPath).OEMName -eq "CircuitPython HID" -or $_.PSChildName -eq "VID_0000&PID_0000"
} | Remove-Item -Recurse
```

For Bluetooth, also remove the pairing and pair again.

### Migrating from the old firmwares

`installieren.py` recognizes the old pedal firmware (v9) and button box (v2) and migrates
them:

1. Enable maintenance mode by hand – the old firmwares cannot do it over the console:
   hold the button while plugging in (pedals **GP3**, button box **GP15**).
2. `python3 installieren.py` – no template needed.

Migrated: pins, Wi-Fi name and password, rumble settings and SimHub names, deadzones and
filters from the old `settings.py`; USB PID, device type and HID axes from the old
`boot.py` (games see the same axes as before); pedal calibration including curves,
button box calibration, logic buttons, suppressed inputs and LED logic. The old files
are moved to **`alt/`** on the board. `--keine-uebernahme` uses the given template
instead.

## Telemetry (SimHub & co.)

The device accepts lines of the form `name=value;name=value` terminated by `\n` on its
**second** serial port (data port; on the ESP32-S3 on the single console port) – from
SimHub, your own script or any other program. In SimHub, add a *Custom Serial Device*
on that port. Names are free-form and usable everywhere: in logic expressions, LED rules,
rumble and the rev light bar.

The rev lights on the wheel need e.g. `rpm`, `rpmmax` and `pit`. As an NCalc formula in
SimHub, roughly:

```
'rpm=' + [Rpms] + ';rpmmax=' + [CarSettings_MaxRPM] + ';pit=' + [PitLimiterOn] + '\n'
```

(Check the property names in SimHub – they differ between versions.)

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| A Sim axis is missing in-game | not supported by the OS, or collides with another axis – see the table above |
| A game sees phantom buttons or a stuck UI cursor | try *Belegung → Allgemein*: untick "USB-Report mit Report-ID" – the device then sends byte-for-byte like the old firmwares, which helps if a game misreads the report ID |
| Web page does not load while the device is plugged into a PC with no game open | fixed: a host that does not poll the device no longer stalls the firmware |
| Bluetooth is slow on a power bank | fixed: reports no longer wait for a USB host that is not there |
| Windows shows "CircuitPython HID" | see *Device name on Windows* |

## Tests on the PC

```
python3 tests/test_firmware.py     # logic, descriptor, pins, calibration, installer …
python3 tests/sim.py buttonbox     # whole device simulated, http://localhost:8765
```

The simulator replaces the CircuitPython modules with stand-ins and the drive with a
temporary directory. The web interface is real; a restart after saving re-runs the
process including `boot.py`. `hid_fehler.txt` in the simulation folder reports HID
reports whose length does not match the descriptor.

## How this was built

UniversalGC was written with AI assistance: the code comes from
[Claude Code](https://claude.ai/code), every commit says so (`Co-Authored-By`). I set the
requirements, built the hardware, tested every step on real devices and decided what
goes in. Without that help I would never have managed a project of this size – I would
still be fighting FreeJoy and hunting for genuine Blue Pills that no longer exist.

How it is checked:
- running daily on three real devices: pedals (Pico W), button box (Pico 2 W) and a
  steering wheel (ESP32-S3, USB and Bluetooth). Many fixes in the history came from
  exactly that – calibration accuracy, USB and Bluetooth timing, Windows device names;
- an automated test suite and a simulator for the whole device (see *Tests on the PC*),
  run by GitHub Actions on every push;
- features that have not run on hardware yet are marked as such in the release notes.

Bug reports and pull requests are welcome – AI-assisted or not, as long as they are
tested.

## License

UniversalGC is licensed under the **GNU General Public License v3.0 or later** (see
[`LICENSE`](LICENSE)). You may use, modify and share it, commercially too – but if you
distribute the firmware, for example on devices you sell, you must provide the complete
source code of your version under the same license.
