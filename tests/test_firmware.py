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


def test_kalib_sweep_genau():
    """Der Weg muss auf den Rohwert stimmen, nicht nur auf ganze Felder."""
    null = 10 * 256 + 200                 # Ruhestellung spaet im Feld 10
    ende = 30 * 256 + 50                  # Anschlag frueh im Feld 30
    s = kalib.Sweep("as5600", null)
    for _ in range(3):
        for r in range(null, ende + 1, 97):
            s.update(r)
        s.update(ende)
        for r in range(ende, null - 1, -97):
            s.update(r)
    st, sp = s.ergebnis()
    check("Sweep genau: Weg = %d (soll %d)" % (sp, ende - null), sp == ende - null)
    c = kalib.cal_default("as5600")
    c["start"], c["span"] = st, sp
    check("Sweep genau: Anschlag ergibt 100 %", kalib.norm(ende, c, 0.015, 0.02) == 1.0)
    # abwaerts, ueber den Nulldurchgang
    null = 2 * 256 + 30
    ende = (null - 4000) % 65536
    s = kalib.Sweep("as5600", null)
    r = null
    for _ in range(4000 // 80):
        r = (r - 80) % 65536
        s.update(r)
    s.update(ende)
    st, sp = s.ergebnis()
    check("Sweep genau abwaerts ueber Null: Weg = %d (soll -4000)" % sp, sp == -4000)


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


def test_pin_suche():
    import suche
    a = suche.Auswertung(["GPIO4", "GPIO10", "GPIO11", "GPIO21"])
    a.ereignis(0, True, 1.0)
    a.ereignis(0, False, 1.2)
    # Encoder an GPIO10/11: abwechselnde Flanken, 3 Rasten
    t = 2.0
    for _ in range(3):
        for i, z in ((1, True), (2, True), (1, False), (2, False)):
            a.ereignis(i, z, t)
            t += 0.02
    a.ereignis(3, True, 2.0)          # Kippschalter, bleibt an
    v = a.vorschlaege(4.5)
    arten = {(e["art"], e["a"]) for e in v}
    check("Suche: Taster erkannt", ("taster", "GPIO4") in arten)
    check("Suche: Encoder erkannt", ("encoder", "GPIO10") in arten)
    check("Suche: Encoder-Pins nicht als Taster", ("taster", "GPIO10") not in arten
          and ("taster", "GPIO11") not in arten)
    check("Suche: gehaltener Schalter erkannt", ("schalter", "GPIO21") in arten)
    # Zwei Taster nacheinander sind kein Encoder
    b = suche.Auswertung(["A", "B"])
    for k in range(5):
        b.ereignis(0, k % 2 == 0, 1.0 + k * 0.1)
    for k in range(5):
        b.ereignis(1, k % 2 == 0, 1.6 + k * 0.1)
    check("Suche: zwei Taster nacheinander kein Encoder", not b.encoder(2.0))

    an = suche.AnalogAuswertung(["GPIO1", "GPIO2"], 0.0)
    for k in range(20):                       # Lernphase: beide ruhig
        an.messung(0, 30000 + k, k * 0.05)
        an.messung(1, 30000 + k * 10, k * 0.05)
    for k in range(40):                       # GPIO1 wird bewegt
        an.messung(0, 5000 + k * 1200, 1.0 + k * 0.05)
        an.messung(1, 30000 + (k % 3) * 100, 1.0 + k * 0.05)
    v = an.vorschlaege()
    check("Suche: Achse erkannt", [e["a"] for e in v] == ["GPIO1"])


def test_installieren():
    import installieren as inst
    v, b, c = inst.boot_out_lesen(
        "Adafruit CircuitPython 10.3.1 on 2026-09-14; VCC-GND YD-ESP32-S3 (N16R8) "
        "with ESP32S3\nBoard ID:yd_esp32_s3_n16r8\n")
    check("boot_out: Version, Board, Chip", (v, b, c) == ("10.3.1", "yd_esp32_s3_n16r8", "esp32s3"))
    _, _, c = inst.boot_out_lesen("Adafruit CircuitPython 10.2.0 on x; Raspberry Pi Pico 2 W with rp2350a\n")
    check("boot_out: rp2350", c == "rp2350")
    check("Bibliotheken Lenkrad", inst.noetige_bibliotheken(preset("lenkrad"), "esp32s3")
          == ["neopixel", "adafruit_ble"])
    check("Bibliotheken Buttonbox: keine", inst.noetige_bibliotheken(preset("buttonbox"), "rp2350") == [])
    check("Bibliotheken Pedale (PIO)", inst.noetige_bibliotheken(preset("pedale"), "rp2040")
          == ["adafruit_pioasm", "adafruit_hx711"])
    check("Bibliotheken HX711 auf ESP32", inst.noetige_bibliotheken(preset("pedale"), "esp32s3")
          == ["adafruit_hx711"])
    kop, weg = inst.plan(FW, "quelltext")
    ziele = [z for _, z in kop]
    check("Installation: boot.py zuletzt", ziele[-1] == "boot.py")
    check("Installation: alle Module dabei", all("%s.py" % m in ziele for m in inst.MODULE))
    check("Installation: alle Pflichtmodule aus boot.py bekannt",
          set(inst.MODULE) | {"code"} == set(_pflicht_aus_boot()))
    check("Installation: alte .mpy werden entfernt", "lib/cfg.mpy" in weg)


class FakeRepl:
    """Verhaelt sich wie die Konsole von CircuitPython: laufendes code.py,
    Strg+C, 'Press any key', REPL mit Echo."""

    def __init__(self, name="Lenkrad", merker=True):
        self.puffer = b""
        self.zustand = "laeuft"
        self.name = name
        self.merker = merker
        self.zeile = b""
        self.wartung = False
        self.neu_geladen = False

    @property
    def in_waiting(self):
        return len(self.puffer)

    def read(self, n):
        d, self.puffer = self.puffer[:n], self.puffer[n:]
        return d

    def write(self, d):
        for ch in d:
            c = bytes([ch])
            if c == b"\x03":
                if self.zustand == "laeuft":
                    self.puffer += (b"Traceback...\r\nKeyboardInterrupt:\r\n\r\nCode done running.\r\n"
                                    b"Press any key to enter the REPL. Use CTRL-D to reload.\r\n")
                    self.zustand = "warten"
            elif c == b"\x04":
                self.neu_geladen = True
                self.zustand = "laeuft"
            elif self.zustand == "warten":
                self.puffer += b"\r\nAdafruit CircuitPython 10.3.1\r\n>>> "
                self.zustand = "repl"
            elif self.zustand == "repl":
                if c == b"\r":
                    self.puffer += self.zeile + b"\r\n" + self._ausfuehren(self.zeile.decode()) + b">>> "
                    self.zeile = b""
                else:
                    self.zeile += c

    def _ausfuehren(self, cmd):
        import installieren as inst
        if cmd == inst.ABFRAGE:
            return ("UGC:%s\r\n" % self.name).encode() if self.name else b"UGC:-\r\n"
        if cmd == inst.WARTUNG:
            if not self.merker:
                return b"ImportError: no module named 'merker'\r\n"
            self.wartung = True
            return b""
        return b""


def test_konsole():
    import installieren as inst
    f = FakeRepl("Lenkrad")
    k = inst.Konsole(f, warte=lambda s: None)
    k.lesen = lambda dauer, k=k: k.s.read(k.s.in_waiting).decode()
    check("Konsole: Name der Belegung", k.name() == "Lenkrad")
    k.weiterlaufen()
    check("Konsole: danach weiterlaufen (Strg+D)", f.neu_geladen and f.zustand == "laeuft")
    f2 = FakeRepl(None)
    k2 = inst.Konsole(f2, warte=lambda s: None)
    k2.lesen = lambda dauer, k=k2: k.s.read(k.s.in_waiting).decode()
    check("Konsole: keine UniversalGC erkannt", k2.name() is None)
    f3 = FakeRepl("Alt", merker=False)
    k3 = inst.Konsole(f3, warte=lambda s: None)
    k3.lesen = lambda dauer, k=k3: k.s.read(k.s.in_waiting).decode()
    k3.zur_repl()
    check("Konsole: alte Firmware ohne merker meldet Fehler", "Error" in k3.befehl(inst.WARTUNG))
    f4 = FakeRepl("Neu")
    k4 = inst.Konsole(f4, warte=lambda s: None)
    k4.lesen = lambda dauer, k=k4: k.s.read(k.s.in_waiting).decode()
    k4.zur_repl()
    k4.befehl(inst.WARTUNG)
    check("Konsole: Wartungsmodus ausgeloest", f4.wartung)
    # Echtes Verhalten: nach merker.wartung() verschwindet der Port
    weg = FakeRepl("Pedale")
    orig = weg._ausfuehren

    def mit_reset(cmd, orig=orig, f=weg):
        r = orig(cmd)
        if f.wartung:
            def kaputt():
                raise OSError(5, "Input/output error")
            type(f).in_waiting = property(lambda self: kaputt())
        return r
    weg._ausfuehren = mit_reset
    fake_serial = types.SimpleNamespace(Serial=lambda *a, **k: weg,
                                        SerialException=Exception)
    weg.close = lambda: None
    sys.modules["serial"] = fake_serial
    alt_konsole = inst.Konsole
    inst.Konsole = lambda s: alt_konsole(s, warte=lambda x: None)
    try:
        check("Wartung: verschwindender Port gilt als Erfolg",
              inst.wartung_ausloesen("/dev/ttyACM0") is None and weg.wartung)
    finally:
        inst.Konsole = alt_konsole
        del sys.modules["serial"]
        del FakeRepl.in_waiting
        FakeRepl.in_waiting = property(lambda self: len(self.puffer))
    check("Konsole: Echo der Abfrage ist kein Treffer",
          "UGC:" in inst.ABFRAGE and not inst.ABFRAGE.startswith("UGC:"))


def test_bundle_eintraege():
    import io
    import zipfile
    import installieren as inst
    puffer = io.BytesIO()
    w = "adafruit-circuitpython-bundle-10.x-mpy-20261014/lib/"
    with zipfile.ZipFile(puffer, "w") as z:
        for n in ("neopixel.mpy", "adafruit_ble/__init__.mpy", "adafruit_ble/a/b.mpy",
                  "adafruit_ble_apple_media.mpy", "adafruit_hx711/hx711.mpy"):
            z.writestr(w + n, b"x")
    with zipfile.ZipFile(puffer) as z:
        ble = sorted(r for r, _ in inst.bundle_eintraege(z, "adafruit_ble"))
        check("Bundle: adafruit_ble komplett, aber kein adafruit_ble_apple_media",
              ble == ["adafruit_ble/__init__.mpy", "adafruit_ble/a/b.mpy"])
        check("Bundle: neopixel", [r for r, _ in inst.bundle_eintraege(z, "neopixel")] == ["neopixel.mpy"])
        check("Bundle: fehlende Bibliothek leer", inst.bundle_eintraege(z, "adafruit_pioasm") == [])


def _alt(art, *namen):
    d = {}
    for n in namen:
        with open(os.path.join(HIER, "alt", art, n)) as f:
            d[n] = f.read()
    return d


def test_uebernahme_pedale():
    import uebernahme
    pico = pins_fuer("rp2040")
    d = _alt("pedale", "settings.py", "boot.py")
    # Kalibrierung, wie Pedale v9 sie schreibt (Weg schon um 2 % gekuerzt)
    d["calibration.json"] = json.dumps([
        {"typ": "adc", "start": 64000, "span": 2940, "curve": [[0, 0], [100, 100]]},
        {"typ": "hx711", "start": 0, "span": 49000, "curve": [[0, 0], [50, 30], [100, 100]]},
        {"min": 1000, "max": 4000, "invert": True}])
    art, neu, hinweise = uebernahme.plan(d)
    c = neu["device.json"]
    check("Uebernahme: Pedale erkannt", art == "pedale")
    check("Uebernahme Pedale: Belegung gueltig %s" % cfg.validate(cfg.normalize(c), pico.pin_id, pico.analog_ok),
          not cfg.validate(cfg.normalize(c), pico.pin_id, pico.analog_ok))
    check("Uebernahme Pedale: Waegezelle auf GP1/GP0", c["axes"][1]["type"] == "hx711"
          and c["axes"][1]["dt"] == "GP1")
    check("Uebernahme Pedale v9.7: Gamepad X/Y/Z wie bisher",
          c["usb"]["usage"] == "gamepad" and [a["usage"] for a in c["axes"]] == ["x", "y", "z"])
    check("Uebernahme Pedale: PID 0x4712", c["usb"]["pid"] == 0x4712)
    check("Uebernahme Pedale: Rumble-Kanaele", [k["tele"] for k in c["rumble"]["channels"]] == ["bremse", "gas"])
    cal = neu["calibration.json"]
    check("Uebernahme Pedale: AS5600 mit Typ as5600", cal[0]["typ"] == "as5600" and cal[0]["start"] == 64000)
    check("Uebernahme Pedale: Weg um die Reserve zurueckgerechnet", cal[0]["span"] == 3000)
    check("Uebernahme Pedale: Kennlinie bleibt", cal[1]["curve"] == [[0, 0], [50, 30], [100, 100]])
    check("Uebernahme Pedale: v8-Datensatz umgerechnet", cal[2]["start"] == 4000 and cal[2]["span"] < 0)
    d2 = _alt("pedale", "settings.py")
    d2["boot.py"] = _alt("pedale", "boot_v99.py")["boot_v99.py"]
    c2 = uebernahme.plan(d2)[1]["device.json"]
    check("Uebernahme Pedale v9.9: Joystick Rx/Ry/Rz",
          c2["usb"]["usage"] == "joystick" and [a["usage"] for a in c2["axes"]] == ["rx", "ry", "rz"])
    c3 = uebernahme.plan(_alt("pedale", "settings.py"))[1]["device.json"]
    check("Uebernahme Pedale ohne boot.py: PID 0x4712, Joystick",
          c3["usb"]["pid"] == 0x4712 and c3["usb"]["usage"] == "joystick")


def test_uebernahme_buttonbox():
    import uebernahme
    pico = pins_fuer("rp2040")
    d = _alt("buttonbox", "settings.py", "boot.py", "calibration_bb.json", "logic_bb.json")
    art, neu, hinweise = uebernahme.plan(d)
    c = neu["device.json"]
    check("Uebernahme: Buttonbox erkannt", art == "buttonbox")
    f = cfg.validate(cfg.normalize(c), pico.pin_id, pico.analog_ok)
    check("Uebernahme Buttonbox: Belegung gueltig %s" % f, not f)
    bl, n, _ = cfg.button_layout(cfg.normalize(c))
    check("Uebernahme Buttonbox: Nummern wie v2.1 (40, Logik ab 23)",
          n == 40 and bl[("logic", 0)] == 22 and bl[("button", 10)] == 10)
    check("Uebernahme Buttonbox: Gamepad mit Rx/Ry/Rz",
          c["usb"]["usage"] == "gamepad" and [a["usage"] for a in c["axes"]] == ["rx", "ry", "rz"])
    lg = neu["logic.json"]
    check("Uebernahme Buttonbox: Logikbuttons", lg["buttons"][1]["expr"] == "AND(b4,b9,b10)"
          and lg["buttons"][1]["enabled"])
    check("Uebernahme Buttonbox: unterdrueckte Inputs", lg["suppress"] == [4, 10])
    check("Uebernahme Buttonbox: LED-Logik", lg["leds"][0] == {"on": "motor", "blink": "AND(b9,b10)"})
    check("Uebernahme Buttonbox: Kalibrierung", neu["calibration.json"][1] == {"typ": "pot", "start": 48, "span": 65487})
    c3 = uebernahme.plan(_alt("buttonbox", "settings.py", "logic_bb.json"))[1]["device.json"]
    check("Uebernahme Buttonbox ohne boot.py: PID 0x4711, Gamepad",
          c3["usb"]["pid"] == 0x4711 and c3["usb"]["usage"] == "gamepad")
    check("Uebernahme: keine alte Firmware", uebernahme.plan({"boot.py": "x"})[0] is None)


def _pflicht_aus_boot():
    import re
    s = open(os.path.join(FW, "boot.py")).read()
    m = re.search(r"PFLICHT = \(([^)]*)\)", s)
    return re.findall(r'"(\w+)"', m.group(1))


def test_merker_schont_flash():
    import merker

    class Nvm(bytearray):
        schreib = 0

        def __setitem__(self, i, v):
            Nvm.schreib += 1
            bytearray.__setitem__(self, i, v)

    nvm = Nvm(b"\xff" * 16)
    sys.modules["microcontroller"] = types.SimpleNamespace(nvm=nvm)
    try:
        merker.setzen(merker.FEHLSTARTS, 0)
        check("NVM: frischer Flash (0xFF) wird fuer 0 nicht beschrieben", Nvm.schreib == 0)
        merker.setzen(merker.FEHLSTARTS, 2)
        merker.setzen(merker.FEHLSTARTS, 2)
        check("NVM: gleicher Wert wird nicht erneut geschrieben", Nvm.schreib == 1)
        check("NVM: Wert gelesen", merker.lesen(merker.FEHLSTARTS) == 2)
    finally:
        del sys.modules["microcontroller"]


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
