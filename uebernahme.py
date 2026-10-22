# SPDX-License-Identifier: GPL-3.0-or-later
"""Uebernahme der alten Einzel-Firmwares (Pedale v9, Buttonbox v2).

Laeuft auf dem PC, als Teil von installieren.py - nicht auf dem Geraet.

Aus den Dateien der alten Firmware auf CIRCUITPY wird gebaut:
  device.json        aus settings.py (Pins, WLAN, Rumble ...) und boot.py
                     (USB-PID, Geraetetyp, HID-Achsen - damit die Zuordnungen
                     im Spiel stimmen)
  calibration.json   Pedale: calibration.json umgerechnet
                     Buttonbox: calibration_bb.json (min/max/invert)
  logic.json         Buttonbox: logic_bb.json (Logikbuttons, LED-Logik,
                     unterdrueckte Inputs)
rumble.json behaelt sein Format und bleibt einfach liegen.

settings.py wird NICHT ausgefuehrt, nur gelesen: es zaehlen nur einfache
Zuweisungen von Werten (Zahlen, Texte, Listen).
"""

import ast
import json
import os
import re

ALT_DATEIEN = ("boot.py", "code.py", "settings.py", "index.html",
               "calibration.json", "calibration_bb.json", "logic_bb.json",
               "rumble.json")


# --- Lesen ------------------------------------------------------------------

def settings_lesen(text):
    """Einfache Zuweisungen NAME = Wert aus einer settings.py."""
    werte = {}
    try:
        baum = ast.parse(text)
    except SyntaxError:
        return werte
    for knoten in baum.body:
        if isinstance(knoten, ast.Assign) and len(knoten.targets) == 1 \
                and isinstance(knoten.targets[0], ast.Name):
            try:
                werte[knoten.targets[0].id] = ast.literal_eval(knoten.value)
            except (ValueError, SyntaxError):
                pass
    return werte


def boot_lesen(text):
    """USB-PID, Geraetetyp und HID-Achsen aus einer alten boot.py."""
    info = {}
    m = re.search(r"^USB_PID\s*=\s*(0x[0-9A-Fa-f]+|-?\d+)", text, re.M)
    if m:
        info["pid"] = int(m.group(1), 0)
    m = re.search(r"usage\s*=\s*0x0([45])", text)
    if m:
        info["usage"] = "joystick" if m.group(1) == "4" else "gamepad"
    namen = {"0": "x", "1": "y", "2": "z", "3": "rx", "4": "ry", "5": "rz"}
    info["achsen"] = [namen[n] for n in re.findall(r"0x09,\s*0x3([0-5])", text)]
    m = re.search(r'product="([^"]+)"', text)
    if m:
        info["product"] = m.group(1)
    return info


def erkennen(dateien):
    """'pedale', 'buttonbox' oder None. dateien: dict Name -> Text."""
    s = dateien.get("settings.py")
    if s is None:
        return None
    if "calibration_bb.json" in dateien or "logic_bb.json" in dateien \
            or "INPUT_PINS" in s:
        return "buttonbox"
    if "ADC_PINS" in s or "BREMSE_TYP" in s:
        return "pedale"
    return None


# --- Belegung ---------------------------------------------------------------

def _usb(b, produkt, achsen_vorgabe, pid, usage):
    # Ohne alte boot.py (z. B. vorher geloescht) gelten die Werte der alten
    # Firmware - sonst bekaeme das Geraet eine andere USB-Kennung.
    usb = {"manufacturer": "SimRacing", "product": b.get("product", produkt),
           "pid": b.get("pid", pid), "usage": b.get("usage", usage)}
    achsen = b.get("achsen") or achsen_vorgabe
    return usb, achsen


def device_pedale(s, b):
    usb, hid = _usb(b, "Pedale", ["rx", "ry", "rz"], 0x4712, "joystick")
    pins = list(s.get("ADC_PINS", ["GP26", "GP27", "GP28"]))
    namen = list(s.get("ACHS_NAMEN", ["Gas", "Bremse", "Kupplung"]))
    dz = s.get("DEADZONE_PCT", 1.5)
    mg = s.get("SWEEP_MARGIN_PCT", 2.0)
    while len(hid) < 3:
        hid.append(["rx", "ry", "rz"][len(hid)])
    achsen = []
    for i in range(3):
        a = {"usage": hid[i], "name": namen[i] if i < len(namen) else "Achse %d" % (i + 1),
             "deadzone": dz, "margin": mg}
        if i == 1 and s.get("BREMSE_TYP", "adc") == "hx711":
            a.update({"type": "hx711", "dt": s.get("HX711_DT", "GP1"),
                      "sck": s.get("HX711_SCK", "GP0"),
                      "mode": s.get("HX711_MODE", "pio"),
                      "filter": s.get("HX_FILTER", 8),
                      "hx_max": s.get("HX711_MAX_DEFAULT", 50000)})
        else:
            a.update({"type": "as5600", "pin": pins[i] if i < len(pins) else ""})
        achsen.append(a)
    c = {
        "name": "Pedale",
        "usb": usb,
        "wifi": {"ssid": s.get("AP_SSID", "Pico-Pedale"),
                 "password": s.get("AP_PASSWORD", "pedale123"),
                 "channel": s.get("AP_CHANNEL", 6), "port": s.get("WEB_PORT", 80)},
        "ble": {"enabled": False},
        "config_pin": s.get("WIFI_BTN_PIN", "GP3"),
        "status_led": s.get("LED_PIN", "GP16"),
        "telemetry": {"enabled": True, "timeout": s.get("TELE_TIMEOUT", 2.0)},
        "options": {"hid_in_wifi": s.get("HID_IM_WLAN", True), "axis_avg": 4},
        "axes": achsen,
    }
    rpins = s.get("RUMBLE_PINS") or []
    if rpins:
        rnamen = list(s.get("RUMBLE_NAMEN", []))
        tnamen = list(s.get("TELE_NAMEN", []))
        c["rumble"] = {
            "channels": [{"in1": p[0], "in2": p[1],
                          "name": rnamen[i] if i < len(rnamen) else "Motor %d" % (i + 1),
                          "tele": (tnamen[i] if i < len(tnamen) else "motor%d" % (i + 1)).lower()}
                         for i, p in enumerate(rpins)],
            "supply": s.get("RUMBLE_VERSORGUNG", 12.0),
            "motor": s.get("RUMBLE_MOTOR_NENN", 12.0),
            "pwm_hz": s.get("RUMBLE_PWM_HZ", 20000),
            "kick_ms": s.get("RUMBLE_KICK_MS", 50),
            "brake_ms": s.get("RUMBLE_BREMS_MS", 80),
            "brake_delay_ms": s.get("RUMBLE_BREMS_VERZUG_MS", 0),
            "tele_max": s.get("TELE_MAX", 100),
        }
    return c


def device_buttonbox(s, b):
    usb, hid = _usb(b, "Buttonbox", ["rx", "ry", "rz"], 0x4711, "gamepad")
    pins = list(s.get("INPUT_PINS", []))
    namen = list(s.get("INPUT_NAMEN", []))
    apins = list(s.get("ACHS_PINS", []))
    anamen = list(s.get("ACHS_NAMEN", []))
    rand = s.get("ACHS_RAND_PCT", 1.0)
    while len(hid) < len(apins):
        hid.append(["rx", "ry", "rz", "x", "y", "z"][len(hid)])
    c = {
        "name": "Buttonbox",
        "usb": usb,
        "wifi": {"ssid": s.get("SSID", "Pico-Buttonbox"),
                 "password": s.get("PASSWORD", "buttonbox123"),
                 "channel": s.get("AP_CHANNEL", 6), "port": s.get("WEB_PORT", 80)},
        "ble": {"enabled": False},
        "config_pin": s.get("WLAN_BTN_PIN", "GP15"),
        "status_led": "",
        "telemetry": {"enabled": s.get("TELEMETRIE", True),
                      "timeout": s.get("TELEMETRIE_TIMEOUT_S", 2.0)},
        "options": {"debounce_ms": int(round(s.get("DEBOUNCE_S", 0.02) * 1000)),
                    "axis_threshold": s.get("ACHS_SCHWELLE", 128),
                    "blink_s": s.get("BLINK_S", 0.5)},
        # Buttonnummern wie v2: Inputs ab 1, Logik ab 23
        "buttons": [{"pin": p, "name": namen[i] if i < len(namen) else "Input %d" % (i + 1),
                     "btn": i + 1} for i, p in enumerate(pins)],
        "axes": [{"type": "pot", "pin": p, "usage": hid[i],
                  "name": anamen[i] if i < len(anamen) else "Achse %d" % (i + 1),
                  "deadzone": rand, "margin": rand} for i, p in enumerate(apins)],
        "logic": {"count": 16, "first": 23},
        "leds": [],
    }
    if s.get("LED_PIN"):
        c["leds"].append({"pin": s["LED_PIN"], "name": "LED"})
    return c


# --- Kalibrierung und Logik --------------------------------------------------

def kalibrierung_pedale(alt, s, c):
    """Pedale v9: start/span wie jetzt, aber der Weg war schon um die
    Sweep-Reserve gekuerzt - die neue Firmware zieht die Reserve bei der
    Auswertung ab. Also wieder auf den gemessenen Weg zurueckrechnen.
    Sehr alte Datensaetze (v8: min/max/invert) werden vorher umgerechnet."""
    if not isinstance(alt, list):
        return None
    mg = s.get("SWEEP_MARGIN_PCT", 2.0) / 100.0
    out = []
    for i, a in enumerate(c["axes"]):
        d = alt[i] if i < len(alt) and isinstance(alt[i], dict) else None
        if d is None:
            out.append(None)
            continue
        if "span" not in d:
            mn, mx = int(d.get("min", 0)), int(d.get("max", 65535))
            if mx < mn:
                mn, mx = mx, mn
            d = dict(d, start=mx if d.get("invert") else mn,
                     span=-(mx - mn) if d.get("invert") else mx - mn)
        span = d["span"]
        if 0 < mg < 0.5:
            span = int(round(span / (1.0 - mg)))
        typ = a["type"]
        e = {"typ": typ, "start": 0 if typ == "hx711" else int(d.get("start", 0)),
             "span": span}
        if isinstance(d.get("curve"), list):
            e["curve"] = d["curve"]
        out.append(e)
    return out


def kalibrierung_buttonbox(alt):
    """Buttonbox v2: min/max/invert -> start/span. Der Rand wirkte schon
    damals erst bei der Auswertung, das passt also direkt."""
    if not isinstance(alt, dict) or not isinstance(alt.get("axes"), list):
        return None
    out = []
    for a in alt["axes"]:
        mn, mx = int(a.get("min", 0)), int(a.get("max", 65535))
        if a.get("invert"):
            out.append({"typ": "pot", "start": mx, "span": -(mx - mn)})
        else:
            out.append({"typ": "pot", "start": mn, "span": mx - mn})
    return out


def logik_buttonbox(alt):
    if not isinstance(alt, dict):
        return None
    lb = [{"name": str(b.get("name", "")), "expr": str(b.get("expr", "")),
           "enabled": bool(b.get("enabled"))}
          for b in alt.get("logic_buttons", []) if isinstance(b, dict)]
    return {"buttons": lb[:16],
            "suppress": [int(x) for x in alt.get("suppress_inputs", [])
                         if str(x).isdigit()],
            "leds": [{"on": str(alt.get("led_logic", "")),
                      "blink": str(alt.get("led_blink_logic", ""))}]}


# --- Gesamt -----------------------------------------------------------------

def plan(dateien):
    """Aus den alten Dateien (dict Name -> Text) die neuen bauen.
    Rueckgabe: (art, {Dateiname: Inhalt als dict/list}, Hinweise) oder
    (None, {}, []) wenn keine alte Firmware erkannt wurde."""
    art = erkennen(dateien)
    if art is None:
        return None, {}, []
    s = settings_lesen(dateien["settings.py"])
    b = boot_lesen(dateien.get("boot.py", ""))
    hinweise = []

    def json_oder_none(name):
        try:
            return json.loads(dateien[name]) if name in dateien else None
        except ValueError:
            hinweise.append("%s nicht lesbar - wird nicht uebernommen" % name)
            return None

    neu = {}
    if art == "pedale":
        c = device_pedale(s, b)
        neu["device.json"] = c
        cal = kalibrierung_pedale(json_oder_none("calibration.json"), s, c)
        if cal and all(x is not None for x in cal):
            neu["calibration.json"] = cal
            hinweise.append("Kalibrierung der Pedale uebernommen")
        elif cal is not None:
            hinweise.append("Kalibrierung unvollstaendig - Pedale bitte neu kalibrieren")
        if "rumble.json" in dateien:
            hinweise.append("Rumble-Einstellungen bleiben (gleiches Format)")
    else:
        c = device_buttonbox(s, b)
        neu["device.json"] = c
        cal = kalibrierung_buttonbox(json_oder_none("calibration_bb.json"))
        if cal:
            neu["calibration.json"] = cal
            hinweise.append("Kalibrierung der Achsen uebernommen")
        lg = logik_buttonbox(json_oder_none("logic_bb.json"))
        if lg:
            neu["logic.json"] = lg
            hinweise.append("Logikbuttons und LED-Logik uebernommen (%d aktiv)" %
                            sum(1 for x in lg["buttons"] if x["enabled"]))
    if b.get("achsen"):
        hinweise.append("HID-Achsen wie bisher: %s (%s)" %
                        (", ".join(b["achsen"]), c["usb"]["usage"]))
    return art, neu, hinweise


def dateien_lesen(ziel):
    out = {}
    for n in ALT_DATEIEN:
        p = os.path.join(ziel, n)
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                out[n] = f.read()
    return out
