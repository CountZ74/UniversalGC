"""Simulator: boot.py und code.py auf dem PC laufen lassen.

    python3 tests/sim.py [preset]        (Port: SIM_PORT, Standard 8765)

Die CircuitPython-Module (board, usb_hid, keypad, analogio, wifi, ...) werden
durch Nachbauten ersetzt, das Dateisystem von CIRCUITPY durch ein temporaeres
Verzeichnis. Der Webserver laeuft echt - die Oberflaeche ist dann unter
http://localhost:8765 erreichbar. Ein "Neustart" startet den Prozess neu,
dabei laeuft boot.py wieder durch, genau wie auf dem Geraet.

Der Nachbau von usb_hid prueft jeden Report gegen die in boot.py angemeldete
Laenge und schreibt Abweichungen nach hid_fehler.txt - das ist die haeufigste
Art, wie eine Aenderung an der Belegung ein Geraet stumm macht.

Nur zum Testen auf dem PC, kommt nicht auf das Geraet.
"""

import builtins
import json
import math
import os
import shutil
import socket
import sys
import time
import types

HIER = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HIER)

PORT = int(os.environ.get("SIM_PORT", "8765"))
ROOT = os.environ.get("SIM_ROOT")

# --- Dateisystem -------------------------------------------------------------

if not ROOT:
    import tempfile
    ROOT = tempfile.mkdtemp(prefix="circuitpy_")
    os.environ["SIM_ROOT"] = ROOT
    for n in ("index.html",):
        shutil.copy(os.path.join(FW, n), ROOT)
    shutil.copytree(os.path.join(FW, "presets"), os.path.join(ROOT, "presets"))
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        shutil.copy(os.path.join(FW, "presets", args[0] + ".json"),
                    os.path.join(ROOT, "device.json"))
    print("CIRCUITPY simuliert in", ROOT)

GERAET = {"device.json", "device.bak.json", "cfg_pending", "calibration.json",
          "logic.json", "rumble.json", "index.html", "presets", "fehler.txt"}


def _map(p):
    if isinstance(p, str) and p.startswith("/"):
        teil = p[1:].split("/", 1)[0]
        if teil in GERAET:
            return os.path.join(ROOT, p[1:])
    return p


_open, _stat, _listdir, _remove = builtins.open, os.stat, os.listdir, os.remove
builtins.open = lambda p, *a, **k: _open(_map(p), *a, **k)
os.stat = lambda p, *a, **k: _stat(_map(p), *a, **k)
os.listdir = lambda p=".": _listdir(_map(p))
os.remove = lambda p: _remove(_map(p))

# --- Nachbauten --------------------------------------------------------------

T0 = time.monotonic()


def mod(name, **kw):
    m = types.ModuleType(name)
    m.__dict__.update(kw)
    sys.modules[name] = m
    return m


class Pin:
    def __init__(self, n):
        self.n = n

    def __repr__(self):
        return "board." + self.n


Pin.__name__ = "Pin"
mc_pin = types.SimpleNamespace()
board = mod("board", board_id="sim_pico_w")
for i in range(29):
    if i in (23, 24, 25):
        continue
    p = Pin("GP%d" % i)
    setattr(mc_pin, "GPIO%d" % i, p)
    setattr(board, "GP%d" % i, p)
board.A0, board.A1, board.A2 = board.GP26, board.GP27, board.GP28
board.LED = Pin("LED")


def reset():
    print("\n*** microcontroller.reset() - Neustart ***\n", flush=True)
    sys.stdout.flush()
    os.execv(sys.executable, [sys.executable] + sys.argv)


mod("microcontroller", pin=mc_pin, reset=reset)
mod("supervisor", set_usb_identification=lambda **kw: print("USB:", kw))
mod("storage", disable_usb_drive=lambda: None, remount=lambda *a, **k: None)
import gc as gc_mod
gc_mod.mem_free = lambda: 123456


class HidDevice:
    def __init__(self, report_descriptor, usage_page, usage, report_ids,
                 in_report_lengths, out_report_lengths):
        self.usage_page = usage_page
        self.usage = usage
        self.laenge = in_report_lengths[0]
        self.ids = report_ids
        self.zahl = 0

    def send_report(self, r, report_id=None):
        if len(r) != self.laenge or (report_id is not None and report_id not in self.ids):
            with _open(os.path.join(ROOT, "hid_fehler.txt"), "a") as f:
                f.write("Report %d Byte, angemeldet %d\n" % (len(r), self.laenge))
            raise ValueError("Reportlaenge")
        self.zahl += 1
        with _open(os.path.join(ROOT, "hid_letzter.txt"), "w") as f:
            f.write(bytes(r).hex())


usb_hid = mod("usb_hid", Device=HidDevice, devices=[])
usb_hid.enable = lambda devs: setattr(usb_hid, "devices", list(devs))
mod("usb_cdc", enable=lambda **kw: None, data=None)


class DigitalInOut:
    def __init__(self, pin):
        self.pin = pin
        self.value = True
        self.direction = None
        self.pull = None

    def deinit(self):
        pass


mod("digitalio", DigitalInOut=DigitalInOut,
    Direction=types.SimpleNamespace(INPUT=0, OUTPUT=1),
    Pull=types.SimpleNamespace(UP=1, DOWN=2))


class AnalogIn:
    """Ein Pedal, das langsam auf und ab geht."""

    def __init__(self, pin):
        self.phase = hash(pin.n) % 7

    @property
    def value(self):
        t = time.monotonic() - T0
        return int(20000 + 15000 * math.sin(t / 3 + self.phase))


mod("analogio", AnalogIn=AnalogIn)


class Ev:
    def __init__(self, k, p):
        self.key_number = k
        self.pressed = p


class Queue:
    def __init__(self, keys):
        self.keys = keys
        self.overflowed = False
        self.q = []

    def get(self):
        self.keys._tick()
        return self.q.pop(0) if self.q else None

    def clear(self):
        self.q = []


class Keys:
    """Druckt Taste 0 alle 2 s. Der Konfigurationstaster (SIM_CFGPIN) wird
    einmal kurz nach dem Start gedrueckt, damit der Access Point angeht."""

    def __init__(self, pins=None, *a, **kw):
        self.pins = pins or []
        self.events = Queue(self)
        self.zust = False
        self.cfg = (len(self.pins) == 1 and
                    getattr(self.pins[0], "n", "") == os.environ.get("SIM_CFGPIN"))
        self.cfg_gedrueckt = False

    def _tick(self):
        t = time.monotonic() - T0
        if self.cfg:
            if not self.cfg_gedrueckt and t > 1.0:
                self.cfg_gedrueckt = True
                self.events.q.append(Ev(0, True))
            return
        z = int(t / 2) % 2 == 1
        if z != self.zust:
            self.zust = z
            self.events.q.append(Ev(0, z))

    def reset(self):
        pass


mod("keypad", Keys=Keys, KeyMatrix=lambda r, c, **kw: Keys(),
    ShiftRegisterKeys=lambda **kw: Keys())


class Encoder:
    def __init__(self, a, b, divisor=4):
        pass

    @property
    def position(self):
        return int((time.monotonic() - T0) / 1.5)


mod("rotaryio", IncrementalEncoder=Encoder)
mod("pwmio", PWMOut=lambda pin, **kw: types.SimpleNamespace(duty_cycle=0))


class StateMachine:
    def __init__(self, *a, **kw):
        self.t = time.monotonic()

    @property
    def in_waiting(self):
        return 1 if time.monotonic() - self.t > 0.0125 else 0

    def readinto(self, buf, end=None):
        self.t = time.monotonic()
        buf[0] = int(30000 + 25000 * math.sin(self.t / 2)) & 0xFFFFFF


mod("rp2pio", StateMachine=StateMachine)
mod("adafruit_pioasm", assemble=lambda s: b"")


class NeoPixel(list):
    def __init__(self, pin, n, **kw):
        super().__init__([(0, 0, 0)] * n)

    def fill(self, c):
        for i in range(len(self)):
            self[i] = c

    def show(self):
        pass


mod("neopixel", NeoPixel=NeoPixel, GRB="GRB", RGB="RGB")


# wifi / socketpool: echte Sockets auf localhost
class Radio:
    def start_ap(self, ssid, password=None, channel=6):
        print("AP:", ssid, password)

    def stop_ap(self):
        print("AP aus")


mod("wifi", radio=Radio())


class SockWrap:
    def __init__(self, s):
        self.s = s

    def setsockopt(self, *a):
        self.s.setsockopt(*a)

    def bind(self, addr):
        self.s.bind(("127.0.0.1", PORT))

    def listen(self, n):
        self.s.listen(n)

    def setblocking(self, b):
        self.s.setblocking(b)

    def accept(self):
        try:
            c, a = self.s.accept()
        except BlockingIOError:
            raise OSError(11)
        return SockWrap(c), a

    def recv_into(self, buf):
        try:
            return self.s.recv_into(buf)
        except BlockingIOError:
            raise OSError(11)

    def send(self, data):
        try:
            return self.s.send(data)
        except BlockingIOError:
            raise OSError(11)

    def close(self):
        self.s.close()


class SocketPool:
    AF_INET = socket.AF_INET
    SOCK_STREAM = socket.SOCK_STREAM
    SOL_SOCKET = socket.SOL_SOCKET
    SO_REUSEADDR = socket.SO_REUSEADDR

    def __init__(self, radio):
        pass

    def socket(self, fam, typ):
        return SockWrap(socket.socket(fam, typ))


mod("socketpool", SocketPool=SocketPool)

# --- Start -------------------------------------------------------------------

sys.platform = os.environ.get("SIM_CHIP", "RP2040")   # wie auf dem Pico
sys.path.insert(0, FW)
try:
    with _open(os.path.join(ROOT, "device.json")) as f:
        os.environ["SIM_CFGPIN"] = json.load(f).get("config_pin", "")
except (OSError, ValueError):
    pass

print("=== boot.py ===")
exec(compile(_open(os.path.join(FW, "boot.py")).read(), "boot.py", "exec"), {"__name__": "boot"})
print("=== code.py ===")
exec(compile(_open(os.path.join(FW, "code.py")).read(), "code.py", "exec"), {"__name__": "code"})
