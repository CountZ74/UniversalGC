# SPDX-License-Identifier: GPL-3.0-or-later
# cfg.py - Geraetekonfiguration von UniversalGC
#
# Ein Geraet - Pedale, Buttonbox, Lenkrad, Flugsim-Panel, Arcade-Stick - wird komplett durch device.json
# beschrieben: welche Funktion an welchem Pin haengt, wie das Geraet am USB
# heisst, welche Buttonnummern es belegt. Vorbild ist FreeJoy, nur dass der
# Konfigurator hier die Weboberflaeche des Geraets selbst ist.
#
# Diese Datei importiert bewusst KEINE Hardware-Module (board, digitalio ...):
# boot.py, code.py und die Tests auf dem PC benutzen sie gleichermassen.
# Was die Hardware braucht - die Frage, ob ein Pin existiert und welche Pins
# nur verschiedene Namen fuer denselben Anschluss sind - kommt als Funktion
# von aussen herein.

import json

CONFIG_FILE  = "/device.json"
BACKUP_FILE  = "/device.bak.json"
PENDING_FILE = "/cfg_pending"       # neue Konfiguration noch nicht bestaetigt

REPORT_ID  = 4
AXIS_MAX   = 65535
MAX_BUTTONS = 128
MAX_AXES    = 8

# HID-Usages der Achsen: Name -> (Usage Page, Usage).
#
# Generic Desktop (0x01) versteht jedes Spiel und Windows zuverlaessig - das
# ist der Normalfall. Die Pedale laufen seit v9.8 mit Rx/Ry/Rz.
#
# Simulation Controls (0x02) beschreiben das Geraet treffender: ein Spiel, das
# sie auswertet, erkennt Bremse und Gas von selbst. Wie Windows und die
# einzelnen Spiele sie zuordnen, ist aber uneinheitlich - je Spiel testen und
# bei Problemen zurueck auf Rx/Ry/Rz. Ausprobiert wurde das schon einmal im
# Pedal-Branch v9.6b-sim-controls (ungetestet geblieben).
#
# "slider" und "toebrake" duerfen zweimal vorkommen (zwei Schieberegler,
# linke und rechte Fussbremse), alles andere nur einmal.
GD = 0x01
SIM = 0x02
AXIS_USAGES = {
    "x": (GD, 0x30), "y": (GD, 0x31), "z": (GD, 0x32),
    "rx": (GD, 0x33), "ry": (GD, 0x34), "rz": (GD, 0x35),
    "slider": (GD, 0x36), "dial": (GD, 0x37), "wheel": (GD, 0x38),
    # Simulation Controls (HID Usage Tables, Page 0x02)
    "aileron": (SIM, 0xB0), "collective": (SIM, 0xB5), "elevator": (SIM, 0xB8),
    "rudder": (SIM, 0xBA), "throttle": (SIM, 0xBB), "toebrake": (SIM, 0xBF),
    "accelerator": (SIM, 0xC4), "brake": (SIM, 0xC5), "clutch": (SIM, 0xC6),
    "steering": (SIM, 0xC8),
}
DOPPELT_ERLAUBT = ("slider", "toebrake")

# Was die Betriebssysteme aus den Achsen machen. Zwei Achsen auf demselben
# Ziel: die zweite faellt weg. None: das System kennt die Achse nicht.
#   Linux:   drivers/hid/hid-input.c - Generic Desktop 0x30..0x38 direkt auf
#            ABS_X..ABS_WHEEL (Slider = ABS_THROTTLE, Dial = ABS_RUDDER),
#            von den Simulation Controls nur Ruder, Throttle, Gas, Bremse,
#            Lenkung; doppelte Codes werden verworfen.
#   Windows: Zuordnung des HID-Treibers fuer DirectInput, wie in MAME
#            (src/osd/modules/input/input_dinput.cpp) beschrieben; Slider
#            gibt es zweimal.
LINUX_ACHSE = {"x": "ABS_X", "y": "ABS_Y", "z": "ABS_Z", "rx": "ABS_RX",
               "ry": "ABS_RY", "rz": "ABS_RZ", "slider": "ABS_THROTTLE",
               "dial": "ABS_RUDDER", "wheel": "ABS_WHEEL",
               "throttle": "ABS_THROTTLE", "rudder": "ABS_RUDDER",
               "accelerator": "ABS_GAS", "brake": "ABS_BRAKE",
               "steering": "ABS_WHEEL"}
WINDOWS_ACHSE = {"x": "X", "y": "Y", "z": "Z", "rx": "Rx", "ry": "Ry", "rz": "Rz",
                 "slider": "Slider", "dial": "Slider", "throttle": "Slider",
                 "rudder": "Rz", "accelerator": "Y", "brake": "Rz", "steering": "X"}


def achsen_hinweise(c):
    """Warnungen, wenn eine Achse unter Linux oder Windows nicht ankommt."""
    h = []
    for system, tabelle, platz in (("Linux", LINUX_ACHSE, {}),
                                   ("Windows", WINDOWS_ACHSE, {"Slider": 2})):
        belegt = {}
        for i, a in enumerate(c["axes"]):
            u = str(a.get("usage", "")).lower()
            name = a.get("name") or "Achse %d" % (i + 1)
            ziel = tabelle.get(u)
            if ziel is None:
                h.append("%s: %s (%s) kennt %s nicht - die Achse fehlt dort"
                         % (system, name, u, system))
                continue
            belegt.setdefault(ziel, []).append(name)
        for ziel, namen in belegt.items():
            if len(namen) > platz.get(ziel, 1):
                h.append("%s: %s landen alle auf %s - nur %s bleibt"
                         % (system, " und ".join(namen), ziel,
                            " und ".join(namen[:platz.get(ziel, 1)])))
    return h

# Joystick statt Gamepad ist der Normalfall: Automobilista 2 und Project CARS
# steuern ihr Menue ueber die X/Y-Achsen von Gamepads (siehe Pedale v9.8).
DEVICE_USAGES = {"joystick": 0x04, "gamepad": 0x05}

AXIS_TYPES = ("pot", "as5600", "hx711", "encoder")
BUTTON_MODES = ("normal", "pulse", "toggle")

# Die Vorgaben fuer ein Geraet ohne device.json. Es meldet sich mit einem
# einzigen Button und startet sofort den Access Point - so kommt man auch ohne
# Konfigurationstaster an die Weboberflaeche (siehe code.py).
def defaults():
    return {
        "name": "UniversalGC",
        "usb": {"manufacturer": "UniversalGC", "product": "UniversalGC",
                "pid": -1, "usage": "joystick"},
        "wifi": {"ssid": "UniversalGC-Setup", "password": "universalgc",
                 "channel": 6, "port": 80},
        "ble": {"enabled": False, "name": ""},
        "config_pin": "",
        # Tastenkombination statt (oder zusaetzlich zu) einem eigenen Taster:
        # Buttonnummern wie am PC (ab 1), gemeinsam "hold" Sekunden halten.
        "config_combo": {"buttons": [], "hold": 3.0},
        "status_led": "",
        "telemetry": {"enabled": True, "timeout": 2.0},
        "options": {"debounce_ms": 20, "axis_threshold": 0,
                    "hid_in_wifi": True, "axis_avg": 4, "blink_s": 0.5},
        "buttons": [],
        "matrix": None,
        "shift": [],
        "encoders": [],
        "selectors": [],
        "axes": [],
        "logic": {"count": 0, "first": 0},
        "leds": [],
        "pixels": None,
        "rumble": None,
    }


def _merge(vorgabe, daten):
    """Fehlende Schluessel aus der Vorgabe ergaenzen, eine Ebene tief.

    Eine aeltere device.json bleibt damit lauffaehig, wenn neue Optionen
    dazukommen. Die Vorgabe wird dabei nicht veraendert (sie ist ohnehin
    jedes Mal frisch gebaut - das war in der Buttonbox v1 ein echter Fehler).
    """
    out = {}
    for k, v in vorgabe.items():
        if k in daten:
            w = daten[k]
            if isinstance(v, dict) and isinstance(w, dict):
                m = dict(v)
                m.update(w)
                out[k] = m
            else:
                out[k] = w
        else:
            out[k] = v
    for k, v in daten.items():
        if k not in out:
            out[k] = v
    return out


def normalize(daten):
    if not isinstance(daten, dict):
        daten = {}
    c = _merge(defaults(), daten)
    for k in ("buttons", "shift", "encoders", "selectors", "axes", "leds"):
        if not isinstance(c.get(k), list):
            c[k] = []
    if not isinstance(c.get("logic"), dict):
        c["logic"] = {"count": 0, "first": 0}
    return c


def _datei_lesen(pfad):
    with open(pfad, "r") as f:
        return json.load(f)


def load(rueckfall=False, leise=False):
    """device.json laden, bei Fehlern die Sicherung, zuletzt die Vorgaben.

    rueckfall=True nimmt gleich die Sicherung (die neue Belegung startete
    nicht). Rueckgabe: (konfiguration, quelle) mit quelle "device", "backup",
    "rueckfall", "entwurf" (wartet im NVM aufs Speichern) oder "default".
    Bei "default" startet code.py den Access Point von selbst.
    """
    if not rueckfall:
        # Eine Belegung, die mangels Schreibrecht im NVM wartet (merker.py),
        # gilt vor der device.json - boot.py meldet das Geraet schon mit ihr an.
        try:
            import merker
            e = merker.entwurf_lesen()
            if e:
                d = json.loads(e)
                if isinstance(d, dict):
                    return normalize(d), "entwurf"
        except (ImportError, ValueError) as ex:
            if not leise:
                print("Entwurf im NVM nicht lesbar:", ex)
    reihe = ((CONFIG_FILE, "device"), (BACKUP_FILE, "backup"))
    if rueckfall:
        reihe = ((BACKUP_FILE, "rueckfall"), (CONFIG_FILE, "device"))
    for pfad, quelle in reihe:
        try:
            return normalize(_datei_lesen(pfad)), quelle
        except (OSError, ValueError) as e:
            # boot.py ruft leise auf: boot_out.txt fasst nur 512 Byte, die
            # sollen fuer die wichtigen Meldungen reichen.
            if not leise:
                print("Konfiguration", pfad, "nicht lesbar:", e)
    return normalize({}), "default"


# --- Buttonnummern -----------------------------------------------------------
#
# Jede Quelle von Buttons bekommt einen Block fester Nummern. Wer im Spiel
# schon Tasten zugeordnet hat, will, dass die Nummern bei einer Umbaute
# stehenbleiben - deshalb kann jede Quelle ihre erste Nummer mit "btn"
# festlegen (1-basiert, wie Windows sie anzeigt). Ohne "btn" geht es mit der
# naechsten freien Nummer weiter.

def _stellungen(st):
    try:
        return max(2, min(32, int(st.get("positions", 8))))
    except (TypeError, ValueError):
        return 8


def button_quellen(c):
    """Liste (art, index, anzahl, gewuenschte_erste_nummer_oder_None)."""
    q = []
    for i, b in enumerate(c["buttons"]):
        q.append(("button", i, 1, b.get("btn")))
    m = c.get("matrix")
    if m and m.get("rows") and m.get("cols"):
        q.append(("matrix", 0, len(m["rows"]) * len(m["cols"]), m.get("btn")))
    for i, s in enumerate(c["shift"]):
        q.append(("shift", i, int(s.get("count", 8)), s.get("btn")))
    for i, e in enumerate(c["encoders"]):
        q.append(("encoder", i, 2, e.get("btn")))
    for i, st in enumerate(c.get("selectors") or []):
        q.append(("stufen", i, _stellungen(st), st.get("btn")))
    lg = c.get("logic") or {}
    n = int(lg.get("count", 0) or 0)
    if n > 0:
        q.append(("logic", 0, n, lg.get("first") or None))
    return q


def combo_bits(c):
    """Bits der Konfig-Tastenkombination. Rueckgabe: (bits, fehler).

    Nur echte Schalter zaehlen (Taster, Matrix, Schieberegister) - Encoder
    geben nur kurze Impulse, Logikbuttons haengen selbst an anderen Buttons.
    """
    k = c.get("config_combo") or {}
    nummern = k.get("buttons") or []
    if not nummern:
        return [], []
    bloecke, _, _ = button_layout(c)
    schalter = set()
    for art, idx, n, _ in button_quellen(c):
        if art in ("button", "matrix", "shift") and (art, idx) in bloecke:
            for b in range(bloecke[(art, idx)], bloecke[(art, idx)] + n):
                schalter.add(b)
    bits, f = [], []
    for nr in nummern:
        try:
            b = int(nr) - 1
        except (TypeError, ValueError):
            f.append("Tastenkombination: '%s' ist keine Buttonnummer" % nr)
            continue
        if b not in schalter:
            f.append("Tastenkombination: Button %s ist kein Taster, Matrix- oder "
                     "Schieberegister-Eingang" % nr)
        elif b not in bits:
            bits.append(b)
    if len(bits) < 2 and not f:
        f.append("Tastenkombination braucht mindestens zwei verschiedene Buttons")
    try:
        if float(k.get("hold", 3.0)) < 0.5:
            f.append("Tastenkombination: Haltezeit mindestens 0,5 s")
    except (TypeError, ValueError):
        f.append("Tastenkombination: Haltezeit ist keine Zahl")
    return bits, f


def zugang(c):
    """Gibt es einen Weg an die Einstellungen ohne automatischen AP?"""
    bits, f = combo_bits(c)
    return bool(c.get("config_pin")) or (bool(bits) and not f)


def button_layout(c):
    """Buttonbloecke zuweisen.

    Rueckgabe: (bloecke, gesamt, fehler)
      bloecke  dict (art, index) -> erstes Bit (0-basiert)
      gesamt   Zahl der Buttons im Descriptor, auf ganze Bytes aufgerundet
      fehler   Liste von Texten bei Ueberschneidungen
    """
    belegt = {}
    bloecke = {}
    fehler = []
    quellen = button_quellen(c)

    # Erst alle festen Nummern, damit automatische Bloecke ihnen ausweichen
    for art, idx, n, wunsch in quellen:
        if not wunsch:
            continue
        try:
            erstes = int(wunsch) - 1
        except (TypeError, ValueError):
            fehler.append("%s %d: Buttonnummer '%s' ungueltig" % (art, idx + 1, wunsch))
            continue
        if erstes < 0:
            fehler.append("%s %d: Buttonnummer muss ab 1 zaehlen" % (art, idx + 1))
            continue
        for b in range(erstes, erstes + n):
            if b in belegt:
                fehler.append("Button %d doppelt: %s %d und %s" %
                              (b + 1, art, idx + 1, belegt[b]))
            belegt[b] = "%s %d" % (art, idx + 1)
        bloecke[(art, idx)] = erstes

    naechstes = 0
    for art, idx, n, wunsch in quellen:
        if wunsch:
            continue
        # Den ersten Platz suchen, an dem der ganze Block frei ist
        while any((b in belegt) for b in range(naechstes, naechstes + n)):
            naechstes += 1
        for b in range(naechstes, naechstes + n):
            belegt[b] = "%s %d" % (art, idx + 1)
        bloecke[(art, idx)] = naechstes
        naechstes += n

    hoechstes = max(belegt) + 1 if belegt else 0
    gesamt = (hoechstes + 7) // 8 * 8
    if gesamt > MAX_BUTTONS:
        fehler.append("%d Buttons - hoechstens %d moeglich" % (hoechstes, MAX_BUTTONS))
    return bloecke, gesamt, fehler


# --- HID-Descriptor ----------------------------------------------------------

def buttons_im_report(c):
    """Buttonzahl im Descriptor. Ein Geraet ganz ohne Eingaenge (frisch, noch
    unkonfiguriert) meldet 8 Buttons - ein leerer Report wird von Windows
    nicht als Spielecontroller angenommen."""
    _, n_btn, _ = button_layout(c)
    if n_btn == 0 and not c["axes"]:
        return 8
    return n_btn


def axis_usages(c):
    """Liste (Usage Page, Usage) in Achsreihenfolge. Unbekanntes wird X."""
    return [AXIS_USAGES.get(str(a.get("usage", "")).lower(), (GD, 0x30))
            for a in c["axes"]]


def _bloecke(usages):
    """Aufeinanderfolgende Achsen derselben Usage Page zusammenfassen.

    Der Report bleibt in Achsreihenfolge; nur wo die Page wechselt, beginnt im
    Descriptor ein neuer Block mit eigener Usage Page.
    """
    out = []
    for page, u in usages:
        if out and out[-1][0] == page:
            out[-1][1].append(u)
        else:
            out.append((page, [u]))
    return out


def ascii_name(text, laenge=126):
    """Fuer USB-Namen, die nur ASCII erlauben: Umlaute umschreiben, Rest weg."""
    ersatz = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}
    out = ""
    for ch in str(text):
        if ch in ersatz:
            out += ersatz[ch]
        elif " " <= ch <= "~":
            out += ch
    return out.strip()[:laenge]


def hid_name(c):
    """So soll das Geraet in den Windows-Gamecontroller-Einstellungen heissen."""
    return ascii_name(c["usb"].get("product") or c.get("name") or "") or "UniversalGC"


def report_id(c):
    """Report-ID fuer USB. 0 = ohne (wie die alten Firmwares) - fuer
    Programme, die die Reports selbst auslesen und sich am zusaetzlichen
    ID-Byte verschlucken (options.report_id = false)."""
    return REPORT_ID if c["options"].get("report_id", True) else 0


def descriptor(c, mit_id=None):
    """HID-Report-Descriptor aus der Konfiguration bauen.

    Aufbau des Reports (ohne Report-ID, die setzt der Stack davor):
      Buttons, 1 bit je Button, auf ganze Bytes aufgerundet
      Achsen,  je 16 bit unsigned 0..65535, little endian
    """
    n_btn = buttons_im_report(c)
    usages = axis_usages(c)
    geraet = DEVICE_USAGES.get(str(c["usb"].get("usage", "joystick")).lower(), 0x04)

    d = bytearray((
        0x05, 0x01,              # Usage Page (Generic Desktop)
        0x09, geraet,            # Usage (Joystick / Gamepad)
        0xA1, 0x01,              # Collection (Application)
    ))
    if mit_id or (mit_id is None and report_id(c)):
        d.extend(bytes((0x85, REPORT_ID)))   # Report ID
    if n_btn:
        d.extend(bytes((
            0x05, 0x09,          #   Usage Page (Button)
            0x19, 0x01,          #   Usage Minimum (1)
            0x29, n_btn,         #   Usage Maximum (n)
            0x15, 0x00,          #   Logical Minimum (0)
            0x25, 0x01,          #   Logical Maximum (1)
            0x75, 0x01,          #   Report Size (1)
            0x95, n_btn,         #   Report Count (n)
            0x81, 0x02,          #   Input (Data, Variable, Absolute)
        )))
    for page, liste in _bloecke(usages):
        d.extend(bytes((0x05, page)))    # Usage Page (Generic Desktop / Simulation)
        for u in liste:
            d.extend(bytes((0x09, u)))   # Usage (X, Rx, Brake ...)
        d.extend(bytes((
            0x15, 0x00,                    #   Logical Minimum (0)
            0x27, 0xFF, 0xFF, 0x00, 0x00,  #   Logical Maximum (65535)
            0x75, 0x10,                    #   Report Size (16)
            0x95, len(liste),              #   Report Count
            0x81, 0x02,                    #   Input (Data, Variable, Absolute)
        )))
    d.append(0xC0)               # End Collection
    return bytes(d)


def report_laenge(c):
    return buttons_im_report(c) // 8 + 2 * len(c["axes"])


def device_usage(c):
    return DEVICE_USAGES.get(str(c["usb"].get("usage", "joystick")).lower(), 0x04)


# --- Pins --------------------------------------------------------------------

def pins_belegt(c):
    """Alle Pins mit ihrer Rolle: Liste (pinname, rolle)."""
    p = []

    def dazu(name, rolle):
        if name:
            p.append((str(name), rolle))

    dazu(c.get("config_pin"), "Konfigurationstaster")
    dazu(c.get("status_led"), "Status-LED")
    for i, b in enumerate(c["buttons"]):
        dazu(b.get("pin"), "Taster %d" % (i + 1))
    m = c.get("matrix")
    if m:
        for i, r in enumerate(m.get("rows", [])):
            dazu(r, "Matrix Zeile %d" % (i + 1))
        for i, s in enumerate(m.get("cols", [])):
            dazu(s, "Matrix Spalte %d" % (i + 1))
    for i, s in enumerate(c["shift"]):
        for k in ("data", "clock", "latch"):
            dazu(s.get(k), "Schieberegister %d %s" % (i + 1, k))
    for i, e in enumerate(c["encoders"]):
        if e.get("type") == "as5600":
            dazu(e.get("pin"), "Encoder %d (AS5600)" % (i + 1))
        else:
            dazu(e.get("a"), "Encoder %d A" % (i + 1))
            dazu(e.get("b"), "Encoder %d B" % (i + 1))
    for i, st in enumerate(c.get("selectors") or []):
        dazu(st.get("pin"), "Stufenschalter %d" % (i + 1))
    for i, a in enumerate(c["axes"]):
        t = a.get("type")
        if t == "hx711":
            dazu(a.get("dt"), "Achse %d HX711 DT" % (i + 1))
            dazu(a.get("sck"), "Achse %d HX711 SCK" % (i + 1))
        elif t == "encoder":
            dazu(a.get("a"), "Achse %d Encoder A" % (i + 1))
            dazu(a.get("b"), "Achse %d Encoder B" % (i + 1))
        else:
            dazu(a.get("pin"), "Achse %d" % (i + 1))
    for i, l in enumerate(c["leds"]):
        dazu(l.get("pin"), "LED %d" % (i + 1))
    px = c.get("pixels")
    if px:
        dazu(px.get("pin"), "WS2812")
    rb = c.get("rumble")
    if rb:
        for i, k in enumerate(rb.get("channels", [])):
            dazu(k.get("in1"), "Rumble %d IN1" % (i + 1))
            dazu(k.get("in2"), "Rumble %d IN2" % (i + 1))
    return p


def validate(c, pin_id=None, analog_ok=None):
    """Konfiguration pruefen. Rueckgabe: Liste von Fehlertexten (leer = gut).

    pin_id(name)    -> eindeutige Kennung des Anschlusses oder None, wenn das
                       Board den Pin nicht kennt. Zwei Namen fuer denselben
                       Anschluss (GP25 und LED) ergeben dieselbe Kennung.
    analog_ok(name) -> False, wenn der Pin kein Analogeingang ist.
    Ohne diese Funktionen werden nur die Namen verglichen.
    """
    f = []
    if pin_id is None:
        def pin_id(n):
            return n

    gesehen = {}
    for name, rolle in pins_belegt(c):
        k = pin_id(name)
        if k is None:
            f.append("%s: Pin %s gibt es auf diesem Board nicht" % (rolle, name))
            continue
        if k in gesehen:
            f.append("Pin %s doppelt belegt: %s und %s" % (name, gesehen[k], rolle))
        else:
            gesehen[k] = rolle

    _, n_btn, bf = button_layout(c)
    f.extend(bf)

    if len(c["axes"]) > MAX_AXES:
        f.append("%d Achsen - hoechstens %d moeglich" % (len(c["axes"]), MAX_AXES))
    zaehl = {}
    for i, a in enumerate(c["axes"]):
        t = a.get("type")
        if t not in AXIS_TYPES:
            f.append("Achse %d: unbekannter Typ '%s'" % (i + 1, t))
            continue
        u = str(a.get("usage", "")).lower()
        if u not in AXIS_USAGES:
            f.append("Achse %d: unbekannte HID-Achse '%s'" % (i + 1, u))
        else:
            zaehl[u] = zaehl.get(u, 0) + 1
        if t in ("pot", "as5600"):
            if not a.get("pin"):
                f.append("Achse %d: kein Pin" % (i + 1))
            elif analog_ok is not None and not analog_ok(a["pin"]):
                f.append("Achse %d: %s ist kein Analogeingang" % (i + 1, a["pin"]))
        elif t == "hx711" and not (a.get("dt") and a.get("sck")):
            f.append("Achse %d: Waegezelle braucht DT und SCK" % (i + 1))
        elif t == "encoder" and not (a.get("a") and a.get("b")):
            f.append("Achse %d: Encoder braucht A und B" % (i + 1))
    for u, n in zaehl.items():
        if n > (2 if u in DOPPELT_ERLAUBT else 1):
            f.append("HID-Achse %s %dx vergeben" % (u, n))

    for i, e in enumerate(c["encoders"]):
        if e.get("type") == "as5600":
            if not e.get("pin"):
                f.append("Encoder %d (AS5600): kein Pin" % (i + 1))
            elif analog_ok is not None and not analog_ok(e["pin"]):
                f.append("Encoder %d: %s ist kein Analogeingang" % (i + 1, e["pin"]))
            try:
                r = int(e.get("detents", 20))
            except (TypeError, ValueError):
                r = 0
            if not 2 <= r <= 64:
                f.append("Encoder %d: Rasten je Umdrehung 2 bis 64" % (i + 1))
        elif not (e.get("a") and e.get("b")):
            f.append("Encoder %d braucht A und B" % (i + 1))
    for i, st in enumerate(c.get("selectors") or []):
        if not st.get("pin"):
            f.append("Stufenschalter %d: kein Pin" % (i + 1))
        elif analog_ok is not None and not analog_ok(st["pin"]):
            f.append("Stufenschalter %d: %s ist kein Analogeingang" % (i + 1, st["pin"]))
        try:
            n = int(st.get("positions", 8))
        except (TypeError, ValueError):
            n = 0
        if not 2 <= n <= 32:
            f.append("Stufenschalter %d: 2 bis 32 Stellungen" % (i + 1))
        elif st.get("type", "as5600") == "as5600" and st.get("step"):
            try:
                if float(st["step"]) * (n - 1) >= 360:
                    f.append("Stufenschalter %d: %d Stellungen zu je %s Grad passen "
                             "nicht auf eine Umdrehung" % (i + 1, n, st["step"]))
            except (TypeError, ValueError):
                f.append("Stufenschalter %d: Abstand ist keine Zahl" % (i + 1))
    for i, b in enumerate(c["buttons"]):
        if not b.get("pin"):
            f.append("Taster %d: kein Pin" % (i + 1))
        if b.get("mode", "normal") not in BUTTON_MODES:
            f.append("Taster %d: unbekannte Betriebsart '%s'" % (i + 1, b.get("mode")))
    m = c.get("matrix")
    if m and (bool(m.get("rows")) != bool(m.get("cols"))):
        f.append("Matrix braucht Zeilen UND Spalten")
    for i, s in enumerate(c["shift"]):
        if not (s.get("data") and s.get("clock") and s.get("latch")):
            f.append("Schieberegister %d braucht data, clock und latch" % (i + 1))
    rb = c.get("rumble")
    if rb:
        for i, k in enumerate(rb.get("channels", [])):
            if not (k.get("in1") and k.get("in2")):
                f.append("Rumble %d braucht IN1 und IN2" % (i + 1))
    px = c.get("pixels")
    if px and px.get("pin"):
        n = int(px.get("count", 0) or 0)
        if n < 1 or n > 256:
            f.append("WS2812: Anzahl %d ungueltig (1 bis 256)" % n)

    u = c["usb"]
    try:
        pid = int(u.get("pid", -1))
        if pid > 0xFFFF:
            f.append("USB-PID zu gross")
    except (TypeError, ValueError):
        f.append("USB-PID ist keine Zahl")
    if str(u.get("usage", "joystick")).lower() not in DEVICE_USAGES:
        f.append("Geraetetyp '%s' unbekannt (joystick oder gamepad)" % u.get("usage"))
    w = c["wifi"]
    pw = w.get("password") or ""
    if pw and len(pw) < 8:
        f.append("WLAN-Passwort braucht mindestens 8 Zeichen (oder leer)")
    _, kf = combo_bits(c)
    f.extend(kf)
    if not c.get("config_pin") and not (c.get("config_combo") or {}).get("buttons"):
        f.append("Weder Konfigurationstaster noch Tastenkombination - ohne "
                 "sie kommt man weder an das WLAN noch an das Laufwerk")
    if n_btn == 0 and not c["axes"]:
        f.append("Weder Buttons noch Achsen - das Geraet haette nichts zu melden")
    return f
