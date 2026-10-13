# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests fuer die universelle Firmware - laufen mit normalem Python auf dem PC.

    python3 tests/test_firmware.py      (oder pytest)

Getestet wird alles, was ohne Hardware geht: Konfiguration, Descriptor,
Buttonnummern, Pinpruefung, Kalibrierung, Logik, Encoder-Impulse,
Betriebsarten der Buttons, Telemetrie, Drehzahlband und Rumble-Kennlinie.
Die Hardware selbst (keypad, pwmio) wird durch kleine Nachbauten ersetzt.
"""

import json
import os
import sys
import types

HIER = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HIER)
sys.path.insert(0, FW)

import cfg        # noqa: E402
import kalib      # noqa: E402
import logik      # noqa: E402
import eingaben   # noqa: E402
import leds       # noqa: E402
from tele import Telemetrie   # noqa: E402
from pins import Pins         # noqa: E402


def preset(name):
    with open(os.path.join(FW, "presets", name + ".json")) as f:
        return cfg.normalize(json.load(f))


# --- Nachbauten --------------------------------------------------------------

class Pin:
    def __init__(self, n):
        self.n = n


def fake_board(chipname):
    """board- und microcontroller.pin-Modul fuer Pico W bzw. ESP32-S3."""
    b = types.SimpleNamespace()
    mc = types.SimpleNamespace()
    if chipname == "rp2040":
        for i in range(29):
            if i in (23, 24, 25):
                continue
            p = Pin("GPIO%d" % i)
            setattr(mc, "GPIO%d" % i, p)
            setattr(b, "GP%d" % i, p)
        b.A0, b.A1, b.A2 = b.GP26, b.GP27, b.GP28
        b.LED = Pin("cyw")
    else:
        for i in list(range(0, 22)) + list(range(26, 49)):
            p = Pin("GPIO%d" % i)
            setattr(mc, "GPIO%d" % i, p)
            setattr(b, "IO%d" % i, p)
    return b, mc


def pins_fuer(chipname):
    b, mc = fake_board(chipname)
    return Pins(b, mc, chipname)


class Ev:
    def __init__(self, k, pressed):
        self.key_number = k
        self.pressed = pressed


class Events:
    def __init__(self):
        self.q = []
        self.overflowed = False

    def get(self):
        return self.q.pop(0) if self.q else None

    def clear(self):
        self.q = []


class FakeKeys:
    alle = []

    def __init__(self, *a, **kw):
        self.events = Events()
        FakeKeys.alle.append(self)

    def reset(self):
        pass


eingaben.keypad = types.SimpleNamespace(Keys=FakeKeys, KeyMatrix=FakeKeys,
                                        ShiftRegisterKeys=FakeKeys)


class FakePort:
    def __init__(self):
        self.daten = b""

    @property
    def in_waiting(self):
        return len(self.daten)

    def read(self, n):
        d, self.daten = self.daten[:n], self.daten[n:]
        return d


# --- HID-Descriptor nachrechnen ---------------------------------------------

def descriptor_bits(d):
    """Einfacher HID-Parser: Summe der Input-Bits und Liste der Usages."""
    i = 0
    size = count = 0
    bits = 0
    usages = []
    rid = None
    while i < len(d):
        b = d[i]
        n = b & 3
        n = 4 if n == 3 else n
        tag = b & 0xFC
        wert = int.from_bytes(bytes(d[i + 1:i + 1 + n]), "little")
        if tag == 0x74:
            size = wert
        elif tag == 0x94:
            count = wert
        elif tag == 0x84:
            rid = wert
        elif tag == 0x08:
            usages.append(wert)
        elif tag == 0x80:
            bits += size * count
        i += 1 + n
    return bits, usages, rid


fehler = []


def check(name, ok):
    print(("ok   " if ok else "FEHL ") + name)
    if not ok:
        fehler.append(name)


# --- Tests -------------------------------------------------------------------

def test_presets_descriptor():
    for name in ("pedale", "buttonbox", "lenkrad"):
        c = preset(name)
        d = cfg.descriptor(c)
        bits, usages, rid = descriptor_bits(d)
        check("%s: Reportlaenge passt zum Descriptor" % name,
              bits == cfg.report_laenge(c) * 8)
        check("%s: Report-ID" % name, rid == cfg.REPORT_ID)
        check("%s: Descriptor endet mit End Collection" % name, d[-1] == 0xC0)
    # Pedale wie v9.9: Joystick, keine Buttons, Rx/Ry/Rz
    c = preset("pedale")
    bits, usages, _ = descriptor_bits(cfg.descriptor(c))
    check("pedale: 6 Byte, nur Achsen", cfg.report_laenge(c) == 6)
    check("pedale: Rx Ry Rz", usages[-3:] == [0x33, 0x34, 0x35])
    check("pedale: Joystick", usages[0] == 0x04)


def test_simulation_controls():
    c = cfg.normalize({"config_pin": "GP15", "axes": [
        {"type": "pot", "pin": "GP26", "usage": "accelerator"},
        {"type": "pot", "pin": "GP27", "usage": "brake"},
        {"type": "pot", "pin": "GP28", "usage": "rx"},
        {"type": "pot", "pin": "A3", "usage": "clutch"}]})
    d = cfg.descriptor(c)
    bits, usages, _ = descriptor_bits(d)
    check("Sim: Reportlaenge passt", bits == cfg.report_laenge(c) * 8 == 64)
    check("Sim: Usages in Achsreihenfolge", usages[1:] == [0xC4, 0xC5, 0x33, 0xC6])
    seiten = [d[i + 1] for i in range(len(d) - 1) if d[i] == 0x05]
    check("Sim: Usage Pages wechseln Sim/GD/Sim", seiten == [0x01, 0x02, 0x01, 0x02])
    p = pins_fuer("rp2040")
    c2 = cfg.normalize({"config_pin": "GP15", "axes": [
        {"type": "pot", "pin": "GP26", "usage": "brake"},
        {"type": "pot", "pin": "GP27", "usage": "brake"}]})
    f = cfg.validate(c2, p.pin_id, p.analog_ok)
    check("Sim: Bremse doppelt erkannt", any("2x" in x for x in f))
    c3 = cfg.normalize({"config_pin": "GP15", "axes": [
        {"type": "pot", "pin": "GP26", "usage": "toebrake"},
        {"type": "pot", "pin": "GP27", "usage": "toebrake"}]})
    check("Sim: zwei Fussbremsen erlaubt", not cfg.validate(c3, p.pin_id, p.analog_ok))


def test_leeres_geraet():
    c = cfg.normalize({})
    check("leeres Geraet meldet 8 Buttons", cfg.buttons_im_report(c) == 8)
    bits, _, _ = descriptor_bits(cfg.descriptor(c))
    check("leeres Geraet: Descriptor stimmt", bits == 8 and cfg.report_laenge(c) == 1)


def test_buttonbox_nummern():
    """Die Buttonnummern muessen zur Buttonbox v2.1 passen, sonst sind alle
    Zuordnungen im Spiel weg."""
    c = preset("buttonbox")
    bl, n, f = cfg.button_layout(c)
    check("buttonbox: keine Fehler", not f)
    check("buttonbox: 40 Buttons wie v2.1", n == 40)
    check("buttonbox: Taster 1 = Bit 0", bl[("button", 0)] == 0)
    check("buttonbox: Zuendung 2 = Bit 10", bl[("button", 10)] == 10)
    check("buttonbox: Logik ab Button 23", bl[("logic", 0)] == 22)


def test_lenkrad_nummern():
    c = preset("lenkrad")
    bl, n, f = cfg.button_layout(c)
    check("lenkrad: keine Fehler", not f)
    check("lenkrad: Matrix ab Button 3", bl[("matrix", 0)] == 2)
    check("lenkrad: Encoder 2 ab Button 21", bl[("encoder", 1)] == 20)
    check("lenkrad: Logik danach (23)", bl[("logic", 0)] == 22)
    check("lenkrad: 32 Buttons im Report", n == 32)


def test_auto_nummern_weichen_aus():
    c = cfg.normalize({"buttons": [{"pin": "GP2"}, {"pin": "GP3", "btn": 2},
                                   {"pin": "GP4"}]})
    bl, n, f = cfg.button_layout(c)
    check("feste Nummer bleibt", bl[("button", 1)] == 1)
    check("automatische Nummer weicht aus", bl[("button", 2)] == 2 and bl[("button", 0)] == 0)
    c = cfg.normalize({"buttons": [{"pin": "GP2", "btn": 5}, {"pin": "GP3", "btn": 5}]})
    _, _, f = cfg.button_layout(c)
    check("doppelte Buttonnummer wird gemeldet", any("doppelt" in x for x in f))


def test_validate_presets():
    pico = pins_fuer("rp2040")
    esp = pins_fuer("esp32s3")
    for name, p in (("pedale", pico), ("buttonbox", pico), ("lenkrad", esp)):
        f = cfg.validate(preset(name), p.pin_id, p.analog_ok)
        check("%s: gueltig %s" % (name, f), not f)
    f = cfg.validate(preset("lenkrad"), pico.pin_id, pico.analog_ok)
    # GPIO21 heisst auf dem Pico GP21 und wird gefunden - aber GPIO1/2 sind
    # dort keine Analogeingaenge
    check("lenkrad auf dem Pico: Analogpins abgelehnt", any("kein Analogeingang" in x for x in f))


def test_validate_fehler():
    p = pins_fuer("rp2040")
    c = cfg.normalize({"buttons": [{"pin": "GP2"}, {"pin": "GP2"}]})
    f = cfg.validate(c, p.pin_id, p.analog_ok)
    check("Pin doppelt erkannt", any("doppelt belegt" in x for x in f))
    c = cfg.normalize({"buttons": [{"pin": "GP26"}],
                       "axes": [{"type": "pot", "pin": "A0", "usage": "x"}]})
    f = cfg.validate(c, p.pin_id, p.analog_ok)
    check("Alias A0 = GP26 erkannt", any("doppelt belegt" in x for x in f))
    c = cfg.normalize({"axes": [{"type": "pot", "pin": "GP5", "usage": "x"}]})
    f = cfg.validate(c, p.pin_id, p.analog_ok)
    check("kein Analogeingang erkannt", any("kein Analogeingang" in x for x in f))
    c = cfg.normalize({"axes": [{"type": "pot", "pin": "GP26", "usage": "x"},
                                {"type": "pot", "pin": "GP27", "usage": "x"}]})
    f = cfg.validate(c, p.pin_id, p.analog_ok)
    check("HID-Achse doppelt erkannt", any("2x" in x for x in f))
    c = cfg.normalize({"buttons": [{"pin": "GP2"}], "wifi": {"password": "kurz"}})
    f = cfg.validate(c, p.pin_id, p.analog_ok)
    check("kurzes WLAN-Passwort erkannt", any("8 Zeichen" in x for x in f))
    c = cfg.normalize({"buttons": [{"pin": "GP2"}]})
    f = cfg.validate(c, p.pin_id, p.analog_ok)
    check("ohne Konfigurationstaster abgelehnt", any("Konfigurationstaster" in x for x in f))
    e = pins_fuer("esp32s3")
    c = cfg.normalize({"buttons": [{"pin": "IO19"}]})
    f = cfg.validate(c, e.pin_id, e.analog_ok)
    check("ESP32-S3: USB-Pin gesperrt", bool(f))
    check("ESP32-S3: IO12 ist ADC2", e.adc2("IO12") and not e.adc2("IO2"))


def test_pin_schreibweisen():
    import pins as pm
    check("Schreibweisen IO21", pm.schreibweisen("IO21") == ["IO21", "GPIO21", "GP21"])
    check("Schreibweisen fremd", pm.schreibweisen("A0") == ["A0"])
    # YD-ESP32-S3: Pins heissen GPIOx, die Vorlage koennte IOx sagen
    b, mc = types.SimpleNamespace(), types.SimpleNamespace()
    for i in list(range(0, 19)) + [21] + list(range(35, 49)):
        pin = Pin("GPIO%d" % i)
        setattr(mc, "GPIO%d" % i, pin)
        setattr(b, "GPIO%d" % i, pin)
    p = Pins(b, mc, "esp32s3")
    check("IO21 findet GPIO21", p.objekt("IO21") is b.GPIO21 and p.pin_id("IO21") == "GPIO21")
    check("IO1 ist analog", p.analog_ok("IO1"))
    f = cfg.validate(preset("lenkrad"), p.pin_id, p.analog_ok)
    check("lenkrad auf YD-ESP32-S3 gueltig %s" % f, not f)
    c = cfg.normalize({"config_pin": "GPIO21", "buttons": [{"pin": "IO4"}, {"pin": "GPIO4"}]})
    f = cfg.validate(c, p.pin_id, p.analog_ok)
    check("IO4 und GPIO4 als doppelt erkannt", any("doppelt belegt" in x for x in f))


def test_pins_json():
    p = pins_fuer("rp2040")
    j = p.json()
    gp26 = [x for x in j if x["n"] == "GP26"][0]
    check("Pinliste: GP26 analog mit Alias A0", gp26["a"] and "A0" in gp26["alias"])
    check("Pinliste: GP2 nicht analog", not [x for x in j if x["n"] == "GP2"][0]["a"])


def test_kalib_as5600_wrap():
    c = {"typ": "as5600", "start": 65000, "span": 2000, "curve": kalib.neue_kurve()}
    check("as5600: Start = 0", kalib.roh_norm(65000, c) == 0.0)
    check("as5600: ueber den Nulldurchgang", abs(kalib.roh_norm(464, c) - 0.5) < 0.001)
    check("as5600: kurz vor Start bleibt 0", kalib.roh_norm(64900, c) == 0.0)
    check("as5600: hinter dem Ende bleibt 1", kalib.roh_norm(2000, c) == 1.0)
    check("kreis_mittel ueber Null", kalib.kreis_mittel([65530, 10]) in (65534, 65535, 0, 2))


def test_kalib_sweep():
    s = kalib.Sweep("as5600", 65000)
    for r in range(65000, 65536 + 3000, 200):
        s.update(r % 65536)
    st, sp = s.ergebnis()
    check("as5600-Sweep: Richtung aufwaerts", sp > 0 and st == 65000)
    check("as5600-Sweep: Weg ca. 3500", 3000 < sp < 4000)

    s = kalib.Sweep("pot", 60000)
    for r in (60000, 40000, 5000, 3000, 30000, 61000):
        s.update(r)
    st, sp = s.ergebnis()
    check("pot-Sweep: Ruhe am Maximum -> faellt", st == 61000 and sp == -58000)
    c = kalib.cal_default("pot")
    c["start"], c["span"] = st, sp
    check("pot: Ruhestellung 0 %", kalib.norm(61000, c) == 0.0)
    check("pot: Anschlag 100 %", kalib.norm(3000, c) == 1.0)
    kalib.flip(c)
    check("pot: Umkehren", kalib.norm(3000, c) == 0.0 and kalib.norm(61000, c) == 1.0)

    s = kalib.Sweep("pot", 1000)
    s.update(1200)
    check("pot-Sweep: zu wenig Bewegung", s.ergebnis() is None)


def test_kalib_raender_kurve():
    c = kalib.cal_default("pot")
    c["start"], c["span"] = 0, 10000
    check("Totzone", kalib.norm(50, c, 0.01, 0.01) == 0.0)
    check("Reserve", kalib.norm(9950, c, 0.01, 0.01) == 1.0)
    check("Mitte", abs(kalib.norm(5000, c, 0.01, 0.01) - 0.5) < 0.001)
    c["curve"] = [[0, 0], [50, 25], [100, 100]]
    check("Kennlinie", kalib.ausgabe(0.5, c) == int(0.25 * 65535 + 0.5))
    check("Ausgabe 0..65535", kalib.ausgabe(1.0, c) == 65535 and kalib.ausgabe(0, c) == 0)
    alt = {"typ": "as5600", "start": 1, "span": 2}
    check("Kalibrierung verworfen bei Typwechsel",
          kalib.cal_passend(alt, "pot")["typ"] == "pot")


class Ctx:
    def __init__(self, bits=(), achsen=(), tele=None):
        self.b = bits
        self.a = achsen
        self.tele = tele or {}

    def button(self, i):
        return i in self.b

    def achse(self, i):
        return self.a[i] if i < len(self.a) else 0.0


def test_logik():
    ctx = Ctx(bits=(9, 10), achsen=(95.0,), tele={"motor": 0.0, "rpm": 7200.0,
                                                   "pit": "True"})
    check("AND", logik.werten("AND(b9,b10)", ctx))
    check("NOT Telemetrie", logik.werten("AND(b9,b10,NOT(motor))", ctx))
    check("GT", logik.werten("GT(rpm,7000)", ctx))
    check("Achse in Prozent", logik.werten("GT(a0,90)", ctx))
    check("Text True", logik.werten("pit", ctx))
    check("Grossschreibung egal", logik.werten("RPM", ctx))
    check("kaputter Ausdruck = False", not logik.werten("AND(b9", ctx))
    check("leer = False", not logik.werten("", ctx))


def test_pulser():
    p = eingaben.Pulser(0.03)
    p.dazu(3)
    t = 0.0
    folge = []
    for _ in range(20):
        r, l = p.schritt(t)
        folge.append(r)
        t += 0.031
    impulse = sum(1 for i in range(1, len(folge)) if folge[i] and not folge[i - 1])
    impulse += 1 if folge[0] else 0
    check("Encoder: 3 Rasten = 3 Impulse", impulse == 3)
    p = eingaben.Pulser(0.03)
    p.dazu(5)
    p.dazu(-1)
    check("Encoder: Richtungswechsel verwirft Rest", p.stau == -1)


def test_eingaben_modi():
    FakeKeys.alle = []
    c = cfg.normalize({"buttons": [
        {"pin": "a"}, {"pin": "b", "mode": "pulse"},
        {"pin": "c", "mode": "toggle"}, {"pin": "d", "invert": True}]})
    bl, n, _ = cfg.button_layout(c)
    e = eingaben.Eingaben(c, bl, n, lambda x: x)
    k = FakeKeys.alle[0]
    e.update(0.0)
    check("Oeffner in Ruhe gedrueckt", e.aus[3] == 1)
    k.events.q = [Ev(0, True), Ev(1, True), Ev(2, True), Ev(3, True)]
    e.update(0.01)
    check("normal: gedrueckt", e.aus[0] == 1)
    check("pulse: Impuls", e.aus[1] == 1)
    check("toggle: an", e.aus[2] == 1)
    check("Oeffner betaetigt: aus", e.aus[3] == 0)
    e.update(0.5)
    check("pulse: Impuls vorbei, Schalter bleibt", e.aus[1] == 0 and e.phys[1] == 1)
    k.events.q = [Ev(1, False), Ev(2, False)]
    e.update(0.6)
    check("pulse: auch beim Ausschalten ein Impuls", e.aus[1] == 1)
    check("toggle: bleibt an nach Loslassen", e.aus[2] == 1)
    k.events.q = [Ev(2, True)]
    e.update(0.7)
    check("toggle: zweiter Druck schaltet aus", e.aus[2] == 0)


def test_telemetrie():
    p = FakePort()
    t = Telemetrie(p, 2.0)
    p.daten = b"Motor=1;rpm=7000\nbremse=4"
    t.lesen(0.0)
    check("Zeile gelesen, Namen klein", t.werte.get("motor") == 1.0 and t.werte["rpm"] == 7000.0)
    t.lesen(1.0)
    check("Zeile ohne Zeilenumbruch nach Pause", t.werte.get("bremse") == 4.0)
    check("verworfen nach Timeout", t.lesen(5.0) and not t.werte)


def test_leds():
    check("farbe", leds.farbe("#ff8000") == (255, 128, 0))
    check("bereich", leds.bereich("0-2,5,99", 10) == [0, 1, 2, 5])
    band, blitz = leds.drehzahlband(0.8, 10, 0.6, 0.97, [(0, 255, 0), (255, 0, 0)])
    an = sum(1 for f in band if f != (0, 0, 0))
    check("Drehzahlband: halb voll", an == 5 and not blitz)
    check("Drehzahlband: unten gruen, oben rot", band[0] == (0, 255, 0) and band[4] == (0, 255, 0))
    band, blitz = leds.drehzahlband(1.0, 10, 0.6, 0.97, [(0, 255, 0)])
    check("Drehzahlband: Schaltblitz", blitz)
    band, _ = leds.drehzahlband(0.3, 10, 0.6, 0.97, [(0, 255, 0)])
    check("Drehzahlband: unter Start alles aus", all(f == (0, 0, 0) for f in band))


def test_rumble_kennlinie():
    import rumble
    rumble.pwmio = types.SimpleNamespace(PWMOut=lambda *a, **k: types.SimpleNamespace(duty_cycle=0))
    r = rumble.Rumble({"channels": [{"in1": "GP4", "in2": "GP5", "tele": "Bremse"}],
                       "supply": 15, "motor": 12}, lambda x: x)
    check("Rumble: Deckel 12/15 V", r.deckel == int(65535 * 12 / 15))
    c = {"schwelle": 10}
    check("Rumble: unter Schwelle aus", r.schwelle(c, 0.05) == 0.0)
    check("Rumble: Schwelle spreizt", abs(r.schwelle(c, 0.55) - 0.5) < 1e-9)
    r.telemetrie({"bremse": 50.0})
    check("Rumble: Telemetriename unabhaengig von Grossschreibung", abs(r.soll[0] - 0.5) < 1e-9)


if __name__ == "__main__":
    for name, f in sorted(globals().items()):
        if name.startswith("test_") and callable(f):
            f()
    print()
    print("%d Fehler" % len(fehler) if fehler else "Alles in Ordnung")
    sys.exit(1 if fehler else 0)
else:
    # unter pytest: jede check-Zeile als assert
    def check(name, ok):     # noqa: F811
        assert ok, name
