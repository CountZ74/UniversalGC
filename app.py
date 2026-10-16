# SPDX-License-Identifier: GPL-3.0-or-later
"""
app.py - UniversalGC v1.0, universelle Gamecontroller-Firmware fuer CircuitPython
=========================================================================

Eine Firmware fuer jede Art von Gamecontroller, nach dem Vorbild von FreeJoy:
Pedale, Buttonbox, Lenkrad, Flugsim-Panel, Arcade-Stick. Was an welchem Pin
haengt, steht in device.json und laesst sich ueber die Weboberflaeche
einstellen. Hervorgegangen aus der Pedal-Firmware v9.9 (Repo sim-pedale) und
der Buttonbox v2.1 (Repo buttonbox); alles, was dort am realen Aufbau
ausgemessen wurde, ist uebernommen:

  - Wraparound-Kalibrierung fuer den AS5600 mit Abdeckungskarte (Pedale v9.3)
  - Waegezelle ueber PIO mit gleitendem Mittel (Pedale v9.5 / v9.7)
  - 16-Bit-Achsen, Joystick statt Gamepad (Pedale v9.6 / v9.8)
  - Rumble im slow-decay-Verfahren mit Totmannschaltung (Pedale v9.7)
  - Logikbuttons und LED-Logik mit SimHub-Telemetrie (Buttonbox v2)
  - nicht blockierender Webserver, statische index.html (beide)

Neu:
  - Tastenmatrix, Schieberegister (74HC165), Encoder, WS2812-Drehzahlband
  - Betriebsarten je Button: normal, Impuls bei Kippschaltern, Umschalter
  - HID-Descriptor wird aus device.json gebaut (boot.py)
  - Bluetooth LE auf dem ESP32-S3 (der Pico W kann unter CircuitPython kein BLE)
  - Belegung in der Weboberflaeche, mit Pruefung und Rueckfall auf die alte

Bedienung
---------
Konfigurationstaster kurz druecken: WLAN-Access-Point an/aus. Mit dem Handy
verbinden und http://192.168.4.1 oeffnen. Der Taster ist zugleich Not-Aus fuer
die Rumble-Motoren. Ohne device.json startet der Access Point von selbst.
Statt des Tasters (oder zusaetzlich) geht eine Tastenkombination
(config_combo): die Buttons gemeinsam halten, bis die Status-LED blinkt.
Beim Einstecken gehalten, oeffnet sie wie der Taster das Laufwerk - das geht
nur mit direkt angeschlossenen Tastern.

Dateien auf CIRCUITPY
---------------------
  boot.py code.py index.html
  app cfg merker pins eingaben achsen kalib logik tele rumble leds ble_hid
  web suche        als .py im Hauptverzeichnis oder als .mpy in lib/
                   (Release-Paket); am einfachsten mit installieren.py
  device.json          die Belegung (aus presets/ kopieren oder im Browser)
  presets/*.json       Vorlagen fuer Pedale, Buttonbox, Lenkrad
  calibration.json     wird angelegt
  logic.json           wird angelegt
  rumble.json          wird angelegt (nur mit Rumble)
  lib/                 siehe README
"""

import time
import gc
import os
import json

import cfg
import merker
import kalib
import logik
from tele import Telemetrie

VERSION = "1.0"
CAL_FILE = "/calibration.json"
LOGIC_FILE = "/logic.json"
BESTAETIGT_NACH = 15.0     # so lange muss eine neue Belegung sauber laufen

CAL_IDLE, CAL_ZERO, CAL_SWEEP, CAL_DONE = "idle", "zero", "sweep", "done"


def json_laden(pfad, vorgabe):
    try:
        with open(pfad) as f:
            return json.load(f)
    except (OSError, ValueError):
        return vorgabe


def json_speichern(pfad, daten):
    try:
        with open(pfad, "w") as f:
            json.dump(daten, f)
        return True
    except OSError as e:
        # Wartungsmodus: boot.py hat das Laufwerk fuer den PC offen gelassen
        print("Speichern fehlgeschlagen:", pfad, e)
        return False


def existiert(pfad):
    try:
        os.stat(pfad)
        return True
    except OSError:
        return False


class Ctx:
    """Was die Logikausdruecke sehen."""

    def __init__(self, app):
        self.app = app
        self.tele = app.tele.werte

    def button(self, i):
        p = self.app.ein.phys if self.app.ein else None
        return bool(p and 0 <= i < len(p) and p[i])

    def achse(self, i):
        w = self.app.ax_pct
        return w[i] if 0 <= i < len(w) else 0.0


class App:
    def __init__(self):
        import board
        import usb_hid
        from pins import Pins

        # Muss dieselbe Belegung sein, mit der boot.py das Geraet angemeldet
        # hat - im Rueckfall also die Sicherung (siehe rueckfall_anwenden).
        self.c, self.quelle = cfg.load(
            merker.lesen(merker.RUECKFALL) == merker.R_MAGIC)
        c = self.c
        self.pins = Pins(board)
        self.fehler = []
        self.neustart_bei = None
        # NVM-Schreibvorgaenge, die bis zum Neustart warten: sie sollen nicht
        # bei laufendem WLAN passieren (der Pico W haelt dafuer den Chip an)
        self.nvm_beim_neustart = {}
        self.entwurf_beim_neustart = None
        self.start_zeit = time.monotonic()
        self.schreibbar = self._schreibtest()

        # --- Buttons ---
        self.bloecke, n_layout, f = cfg.button_layout(c)
        self.fehler.extend(f)
        self.n_btn = cfg.buttons_im_report(c)
        n_intern = max(self.n_btn, n_layout)
        from eingaben import Eingaben
        self.ein = Eingaben(c, self.bloecke, n_intern, self.pins.objekt)
        self.fehler.extend(self.ein.fehler)
        lg_cfg = c.get("logic") or {}
        self.n_logik = int(lg_cfg.get("count", 0) or 0)
        self.logik_bit = self.bloecke.get(("logic", 0), 0)
        self.logik_an = [False] * self.n_logik

        # --- Achsen ---
        from achsen import Achse
        gespeichert = json_laden(CAL_FILE, [])
        if not isinstance(gespeichert, list):
            gespeichert = []
        self.achsen = []
        self.cal = []
        mittel = c["options"].get("axis_avg", 4)
        for i, a in enumerate(c["axes"]):
            typ = a.get("type", "pot")
            alt = gespeichert[i] if i < len(gespeichert) else None
            k = kalib.cal_passend(alt, typ, a.get("hx_max", 50000))
            self.cal.append(k)
            ach = Achse(a, self.pins.objekt, k, mittel)
            if ach.fehler:
                self.fehler.append(ach.fehler)
            if typ in ("pot", "as5600") and self.pins.adc2(a.get("pin")):
                self.fehler.append("%s: %s misst nicht, solange WLAN an ist (ADC2)"
                                   % (ach.name, a.get("pin")))
            self.achsen.append(ach)
        self.ax_roh = [0] * len(self.achsen)
        self.ax_pct = [0.0] * len(self.achsen)
        self.ax_hid = [0] * len(self.achsen)

        # Kalibrierzustand
        self.cal_zustand = CAL_IDLE
        self.cal_achse = None
        self.cal_meldung = ""
        self.sweep = None

        # --- Telemetrie ---
        port = None
        if c["telemetry"].get("enabled", True):
            try:
                import usb_cdc
                port = usb_cdc.data
            except ImportError:
                pass
            if port is None:
                # Kein eigener Datenkanal (ESP32-S3, siehe boot.py): SimHub
                # schickt an die Konsole
                try:
                    from tele import KonsolenPort
                    port = KonsolenPort()
                except Exception as e:
                    self.fehler.append("Telemetrie nicht moeglich: %s" % e)
        self.tele = Telemetrie(port, c["telemetry"].get("timeout", 2.0))
        self.ctx = Ctx(self)

        # --- Logik (logic.json, live aenderbar) ---
        self.lg = self._logik_laden()

        # --- Rumble ---
        self.rumble = None
        if c.get("rumble") and c["rumble"].get("channels"):
            from rumble import Rumble
            self.rumble = Rumble(c["rumble"], self.pins.objekt)
            self.fehler.extend(self.rumble.fehler)

        # --- LEDs ---
        from leds import Leds
        self.leds = Leds(c, self.pins.objekt, self.lg)
        self.fehler.extend(self.leds.fehler)
        # Ohne eigene Status-LED die LED auf dem Board (Pico W: board.LED),
        # sofern sie nicht anders belegt ist. Sie blinkt, solange der Access
        # Point laeuft - so sieht man das auch ohne Konsole.
        self.status = None
        led_pin = c.get("status_led")
        if not led_pin and hasattr(board, "LED"):
            belegt = [n for n, _ in cfg.pins_belegt(c)]
            if "LED" not in belegt:
                led_pin = "LED"
        if led_pin:
            try:
                import digitalio
                self.status = digitalio.DigitalInOut(self.pins.objekt(led_pin))
                self.status.direction = digitalio.Direction.OUTPUT
            except Exception as e:
                self.fehler.append("Status-LED: %s" % e)

        # --- Konfigurationstaster ---
        self.taster = None
        if c.get("config_pin"):
            try:
                import keypad
                self.taster = keypad.Keys([self.pins.objekt(c["config_pin"])],
                                          value_when_pressed=False, pull=True,
                                          interval=0.03)
            except Exception as e:
                self.fehler.append("Konfigurationstaster: %s" % e)
        self.combo, kf = cfg.combo_bits(c)
        if kf:
            self.fehler.extend(kf)
            self.combo = []
        self.combo_halten = float((c.get("config_combo") or {}).get("hold", 3.0))
        self.combo_seit = None
        self.combo_erledigt = False

        # --- HID ---
        self.usage = cfg.device_usage(c)
        self.hid = None
        for d in usb_hid.devices:
            if d.usage_page == 0x01 and d.usage == self.usage:
                self.hid = d
                break
        if self.hid is None:
            self.fehler.append("Kein HID-Geraet - boot.py nicht durchgelaufen? "
                               "Grund steht in boot_out.txt")
        self.report = bytearray(cfg.report_laenge(c))
        self.letzter = bytearray(len(self.report))
        self.letzte_ax = [-1] * len(self.achsen)
        self.schwelle = c["options"].get("axis_threshold", 0)
        self.hid_im_wlan = c["options"].get("hid_in_wifi", True)

        from ble_hid import BleHid
        self.ble = BleHid(c, cfg.descriptor(c), self.usage)
        self.ble.start()

        from web import Web
        self.web = Web(self)
        from suche import PinSuche
        self.suche = PinSuche(self)

        # Der Web-Installer fuer den ESP32 traegt das Heim-WLAN in
        # settings.toml ein. CircuitPython verbindet sich dann selbst und
        # startet seinen Web-Editor auf Port 80 - genau dem Port der
        # Weboberflaeche. Der Access Point kommt dann nicht hoch.
        if os.getenv("CIRCUITPY_WIFI_SSID"):
            self.fehler.append(
                "settings.toml enthaelt CIRCUITPY_WIFI_SSID: CircuitPython "
                "verbindet sich selbst mit dem WLAN und belegt Port 80 - der "
                "Access Point startet dann nicht. Die WLAN-Zeilen in "
                "settings.toml auskommentieren.")

        for f in self.fehler:
            print("Hinweis:", f)

    # --- Hilfen ---

    def _schreibtest(self):
        try:
            with open(CAL_FILE, "a"):
                pass
            return True
        except OSError:
            print("Dateisystem schreibgeschuetzt - nichts wird gespeichert")
            return False

    def _logik_laden(self):
        c = self.c
        d = json_laden(LOGIC_FILE, {})
        if not isinstance(d, dict):
            d = {}
        vorlage = (c.get("logic") or {}).get("buttons", [])
        lb = d.get("buttons") if isinstance(d.get("buttons"), list) else vorlage
        lb = [dict(x) for x in lb if isinstance(x, dict)]
        while len(lb) < self.n_logik:
            lb.append({"name": "Logik %d" % (len(lb) + 1), "expr": "",
                       "enabled": False})
        d["buttons"] = lb[:self.n_logik]
        if not isinstance(d.get("suppress"), list):
            d["suppress"] = list((c.get("logic") or {}).get("suppress", []))
        le = d.get("leds") if isinstance(d.get("leds"), list) else []
        for i, l in enumerate(c["leds"]):
            if i >= len(le) or not isinstance(le[i], dict):
                le.append({"on": l.get("on", ""), "blink": l.get("blink", "")})
        d["leds"] = le[:len(c["leds"])]
        px = d.get("pixels") if isinstance(d.get("pixels"), dict) else {}
        pc = c.get("pixels") or {}
        for k, v in (("rpm", pc.get("rpm", "")), ("rpm_max", pc.get("rpm_max", 100)),
                     ("start", pc.get("start", 60)), ("flash", pc.get("flash", 97)),
                     ("colors", pc.get("colors", ["#00ff00", "#ffff00", "#ff0000"])),
                     ("flash_color", pc.get("flash_color", "#0000ff")),
                     ("rules", pc.get("rules", []))):
            px.setdefault(k, v)
        d["pixels"] = px
        return d

    def button_namen(self):
        """Beschriftung je Bit fuer die Weboberflaeche."""
        n = [""] * max(self.n_btn, len(self.ein.phys))
        c = self.c

        def setz(bit, text):
            if 0 <= bit < len(n):
                n[bit] = text

        for i, b in enumerate(c["buttons"]):
            setz(self.bloecke.get(("button", i), -1),
                 b.get("name") or "Taster %s" % b.get("pin"))
        m = c.get("matrix")
        if m and ("matrix", 0) in self.bloecke:
            namen = m.get("names") or []
            sp = len(m.get("cols", []))
            for k in range(len(m.get("rows", [])) * sp):
                setz(self.bloecke[("matrix", 0)] + k,
                     namen[k] if k < len(namen) and namen[k]
                     else "Matrix %d/%d" % (k // sp + 1, k % sp + 1))
        for i, s in enumerate(c["shift"]):
            namen = s.get("names") or []
            for k in range(int(s.get("count", 8))):
                setz(self.bloecke[("shift", i)] + k,
                     namen[k] if k < len(namen) and namen[k]
                     else "SR%d.%d" % (i + 1, k + 1))
        for i, e in enumerate(c["encoders"]):
            nm = e.get("name") or "Encoder %d" % (i + 1)
            setz(self.bloecke[("encoder", i)], nm + " rechts")
            setz(self.bloecke[("encoder", i)] + 1, nm + " links")
        for i, b in enumerate(self.lg["buttons"]):
            setz(self.logik_bit + i, "L: " + (b.get("name") or ""))
        return n

    # --- Eine Runde ---

    def schritt(self, now):
        """Eingaben lesen, HID senden, Rumble und LEDs. Blockiert nie.

        Wird auch aus dem Webserver heraus aufgerufen, waehrend der auf einen
        Browser wartet - deshalb laeuft das Geraet dann trotzdem weiter.
        """
        self.ein.update(now)
        self.suche.schritt(now)

        if self.tele.lesen(now) and self.rumble:
            for k in range(self.rumble.n):
                self.rumble.soll[k] = 0.0
        if self.rumble:
            if self.tele.werte:
                self.rumble.telemetrie(self.tele.werte)
            self.rumble.step()

        # Achsen
        for i, a in enumerate(self.achsen):
            if self.cal_zustand == CAL_SWEEP and i == self.cal_achse:
                raw = a.roh()
                self.sweep.update(raw)
            else:
                raw = a.roh_mittel()
            self.ax_roh[i] = raw
            n = a.norm(raw)
            self.ax_pct[i] = n * 100.0
            self.ax_hid[i] = kalib.ausgabe(n, self.cal[i])
            if a.hx is not None:
                a.hx.rate_messen(now)

        # Logikbuttons auf die physischen Zustaende
        aus = self.ein.aus
        for i, b in enumerate(self.lg["buttons"]):
            an = bool(b.get("enabled") and b.get("expr")
                      and logik.werten(b["expr"], self.ctx))
            self.logik_an[i] = an
            bit = self.logik_bit + i
            if bit < len(aus):
                aus[bit] = 1 if an else 0

        if not self.web.aktiv or self.hid_im_wlan:
            self._senden()

        self.leds.update(self.ctx, now)
        self._status_led(now)
        if self.ble.radio is not None:
            self.ble.schritt(now)

    def _senden(self):
        r = self.report
        nb = self.n_btn // 8
        for i in range(nb):
            r[i] = 0
        aus = self.ein.aus
        weg = self.lg["suppress"]
        for bit in range(min(self.n_btn, len(aus))):
            if aus[bit] and bit not in weg:
                r[bit >> 3] |= 1 << (bit & 7)
        neu_ax = False
        for i, v in enumerate(self.ax_hid):
            d = v - self.letzte_ax[i]
            if d < 0:
                d = -d
            if d > self.schwelle or (v in (0, kalib.AXIS_MAX) and d):
                neu_ax = True
        if not neu_ax and r[:nb] == self.letzter[:nb]:
            return
        for i, v in enumerate(self.ax_hid):
            r[nb + 2 * i] = v & 0xFF
            r[nb + 2 * i + 1] = (v >> 8) & 0xFF
            self.letzte_ax[i] = v
        self.letzter[:] = r
        if self.hid is not None:
            try:
                self.hid.send_report(r, cfg.REPORT_ID)
            except (OSError, ValueError):
                pass
        self.ble.senden(r)

    def _status_led(self, now):
        if self.status is None:
            return
        if self.web.aktiv:
            takt = 0.08 if self.cal_zustand == CAL_SWEEP else 0.25
            v = int(now / takt) % 2 == 0
        else:
            v = False
        if self.status.value != v:
            self.status.value = v

    def status_blinken(self, n, an=0.15, aus=0.15):
        if self.status is None:
            return
        for _ in range(n):
            self.status.value = True
            time.sleep(an)
            self.status.value = False
            time.sleep(aus)

    # --- Kalibrierung ---

    def _achse_ok(self, a):
        return a is not None and 0 <= a < len(self.achsen)

    def cal_start(self, a):
        if self._achse_ok(a) and self.achsen[a].typ != "encoder":
            self.cal_achse = a
            self.cal_zustand = CAL_ZERO
            self.cal_meldung = ""

    def cal_zero(self):
        if self.cal_achse is None or self.cal_zustand != CAL_ZERO:
            return
        a = self.achsen[self.cal_achse]
        if self.rumble:
            self.rumble.alles_aus()        # waehrend der Wegmessung nicht ruetteln
        if a.hx is not None:
            a.hx.tarieren()
            null = 0
        else:
            null = a.roh_mittel(16)
        self.sweep = kalib.Sweep(a.typ, null)
        self.cal_zustand = CAL_SWEEP

    def cal_finish(self):
        if self.cal_achse is None or self.cal_zustand != CAL_SWEEP:
            return
        i = self.cal_achse
        e = self.sweep.ergebnis()
        if e is None:
            self.cal_meldung = "Zu wenig Bewegung erkannt - ganz durchbewegen"
            return
        self.cal[i]["start"], self.cal[i]["span"] = e
        ok = self._cal_speichern()
        self.cal_meldung = "%s: Weg %d %s%s" % (
            self.achsen[i].name, abs(e[1]), "aufwaerts" if e[1] > 0 else "abwaerts",
            "" if ok else " (nur im RAM, Dateisystem schreibgeschuetzt)")
        self.cal_zustand = CAL_DONE
        self.cal_achse = None
        self.sweep = None

    def cal_abort(self):
        self.cal_zustand = CAL_IDLE
        self.cal_achse = None
        self.cal_meldung = ""
        self.sweep = None

    def cal_reset(self, a):
        if not self._achse_ok(a):
            return
        k = self.cal[a].get("curve")
        acfg = self.c["axes"][a]
        neu = kalib.cal_default(acfg.get("type", "pot"), acfg.get("hx_max", 50000))
        if k:
            neu["curve"] = k
        self.cal[a].clear()
        self.cal[a].update(neu)          # Achse haelt eine Referenz darauf
        self._cal_speichern()
        self.cal_meldung = self.achsen[a].name + " zurueckgesetzt"

    def cal_flip(self, a):
        if self._achse_ok(a):
            kalib.flip(self.cal[a])
            self._cal_speichern()

    def tarieren(self, a):
        if self._achse_ok(a) and self.achsen[a].hx is not None:
            t = self.achsen[a].hx.tarieren()
            self.cal_meldung = "Waegezelle tariert: %d" % t

    def kurve_setzen(self, a, punkte):
        if not self._achse_ok(a) or not isinstance(punkte, list) or len(punkte) < 2:
            return False
        try:
            k = [[int(p[0]), int(p[1])] for p in punkte][:16]
        except (TypeError, ValueError, IndexError):
            return False
        self.cal[a]["curve"] = k
        return self._cal_speichern()

    def _cal_speichern(self):
        return json_speichern(CAL_FILE, self.cal)

    # --- Logik ---

    def logik_setzen(self, d):
        if not isinstance(d, dict):
            return False, ["kein Objekt"]
        lg = self.lg
        if isinstance(d.get("buttons"), list):
            for i, b in enumerate(d["buttons"][:self.n_logik]):
                if isinstance(b, dict):
                    lg["buttons"][i] = {"name": str(b.get("name", ""))[:40],
                                        "expr": str(b.get("expr", ""))[:200],
                                        "enabled": bool(b.get("enabled"))}
        if isinstance(d.get("suppress"), list):
            lg["suppress"] = [int(x) for x in d["suppress"]
                              if str(x).isdigit() and int(x) < self.n_btn]
        if isinstance(d.get("leds"), list):
            for i, l in enumerate(d["leds"][:len(lg["leds"])]):
                if isinstance(l, dict):
                    lg["leds"][i] = {"on": str(l.get("on", ""))[:200],
                                     "blink": str(l.get("blink", ""))[:200]}
        if isinstance(d.get("pixels"), dict):
            lg["pixels"].update(d["pixels"])
        return json_speichern(LOGIC_FILE, lg), []

    # --- Geraetekonfiguration ---

    def config_pruefen(self, text):
        try:
            neu = cfg.normalize(json.loads(text))
        except (ValueError, TypeError) as e:
            return {"ok": False, "f": ["JSON fehlerhaft: %s" % e]}
        f = cfg.validate(neu, self.pins.pin_id, self.pins.analog_ok)
        _, n, _ = cfg.button_layout(neu)
        return {"ok": not f, "f": f,
                "info": "%d Buttons, %d Achsen, %d Byte Report" %
                        (cfg.buttons_im_report(neu), len(neu["axes"]),
                         cfg.report_laenge(neu))}

    def config_speichern(self, text):
        r = self.config_pruefen(text)
        if not r["ok"]:
            return r
        neu = cfg.normalize(json.loads(text))
        if not self.schreibbar:
            # Das Laufwerk gehoert gerade dem PC (Einrichtung, Wartung, oder
            # nach dem Kopieren noch kein echter Neustart). Dann wartet die
            # Belegung im NVM, boot.py meldet sich beim Neustart mit ihr an
            # und sperrt das Laufwerk, entwurf_anwenden() schreibt sie.
            t = json.dumps(neu)
            if not cfg.zugang(neu):
                return {"ok": False, "f": [
                    "Das Laufwerk CIRCUITPY ist fuer den PC freigegeben, und "
                    "die neue Belegung hat weder Konfigurationstaster noch "
                    "Tastenkombination - so koennte das Geraet auch nach dem "
                    "Neustart nicht speichern."]}
            if len(t) > merker.entwurf_platz():
                return {"ok": False, "f": [
                    "Laufwerk CIRCUITPY ist fuer den PC freigegeben, und die "
                    "Belegung ist zu gross fuer den Zwischenspeicher (%d Byte, "
                    "Platz %d). device.json am PC auf das Laufwerk kopieren."
                    % (len(t), merker.entwurf_platz())]}
            self.entwurf_beim_neustart = t
            self.neustart_bei = time.monotonic() + 1.0
            r["neustart"] = True
            r["entwurf"] = True
            return r
        try:
            if existiert(cfg.CONFIG_FILE) and self.quelle == "device":
                with open(cfg.CONFIG_FILE) as f:
                    alt = f.read()
                with open(cfg.BACKUP_FILE, "w") as f:
                    f.write(alt)
            with open(cfg.CONFIG_FILE, "w") as f:
                json.dump(neu, f)
            with open(cfg.PENDING_FILE, "w") as f:
                f.write("0")
            self.nvm_beim_neustart[merker.FEHLSTARTS] = 0
        except OSError as e:
            return {"ok": False, "f": ["Speichern fehlgeschlagen: %s" % e]}
        self.neustart_bei = time.monotonic() + 1.0
        r["neustart"] = True
        return r

    def neustart_hilft(self):
        """Gibt ein normaler Neustart das Dateisystem frei? Nicht, wenn
        boot.py wieder in die Einrichtung ginge (keine device.json, weder
        Taster noch Kombination)."""
        return self.quelle != "default" and cfg.zugang(self.c)

    def wartung_anfordern(self):
        """Beim naechsten Start bleibt CIRCUITPY sichtbar (einmalig).
        Geschrieben wird erst direkt vor dem Neustart, nach dem WLAN."""
        if not merker.verfuegbar():
            return False
        self.nvm_beim_neustart[merker.WARTUNG] = merker.W_MAGIC
        return True

    def bestaetigen(self, now):
        """Neue Belegung laeuft sauber - Rueckfall-Markierung loeschen."""
        if self.start_zeit is None or now - self.start_zeit < BESTAETIGT_NACH:
            return
        if self.web.aktiv:
            return          # erst wenn das WLAN aus ist - kein Flash-Schreiben dabei
        self.start_zeit = None
        if existiert(cfg.PENDING_FILE):
            merker.setzen(merker.FEHLSTARTS, 0)
            try:
                os.remove(cfg.PENDING_FILE)
                print("Neue Belegung bestaetigt")
            except OSError:
                pass

    # --- JSON fuer die Oberflaeche ---

    def init_json(self):
        import sys
        try:
            presets = sorted(n[:-5] for n in os.listdir("/presets") if n.endswith(".json"))
        except OSError:
            presets = []
        try:
            import board
            board_id = board.board_id
        except (ImportError, AttributeError):
            board_id = "?"
        rb = self.rumble
        return {
            "v": VERSION, "name": self.c.get("name"), "q": self.quelle,
            "chip": self.pins.chip, "board": board_id, "plat": sys.platform,
            "pins": self.pins.json(), "c": self.c, "presets": presets,
            "bn": self.button_namen(), "nb": self.n_btn, "lb0": self.logik_bit,
            "an": [a.name for a in self.achsen],
            "at": [a.typ for a in self.achsen],
            "cv": [k.get("curve", kalib.DEFAULT_CURVE) for k in self.cal],
            "lg": self.lg, "ln": [l.get("name") or l.get("pin") for l in self.c["leds"]],
            "px": self.leds.px_n,
            "rn": [k.get("name", "?") for k in rb.kanaele] if rb else [],
            "rt": [k.get("tele", "") for k in rb.kanaele] if rb else [],
            "rc": rb.cfg if rb else [], "rd": bool(rb and rb.da),
            "f": self.fehler, "fs": self.schreibbar, "nh": self.neustart_hilft(),
        }

    def data_json(self):
        def bits(b):
            return "".join("1" if x else "0" for x in b)
        d = {
            "p": bits(self.ein.phys), "o": bits(self.ein.aus),
            "r": self.ax_roh,
            "i": [int(x) for x in self.ax_pct],
            "o2": [a.prozent_aus(self.ax_roh[i]) for i, a in enumerate(self.achsen)],
            "c": [[k["start"], k["span"]] for k in self.cal],
            "hz": [a.hx.rate if a.hx else 0 for a in self.achsen],
            "st": self.cal_zustand, "ax": self.cal_achse, "m": self.cal_meldung,
            "sw": list(self.sweep.wege()) if self.sweep else [0, 0],
            "lb": [1 if x else 0 for x in self.logik_an],
            "led": self.leds.zustand,
            "enc": self.ein.encoder_positionen(),
            "rb": [int(x * 100) for x in self.rumble.ist] if self.rumble else [],
            "ble": self.ble.status(), "fs": self.schreibbar,
            "mem": gc.mem_free(),
        }
        d.update(self.tele.json())
        return d

    # --- Hauptschleife ---

    def wlan_umschalten(self):
        if self.rumble:
            self.rumble.not_aus()    # Taster ist immer zuerst Not-Aus
        if self.web.aktiv:
            self.web.stoppen = True
            return
        self.ble.pause()
        try:
            self.web.starten()
            self.ap_wunsch = False
            self.status_blinken(2, 0.1, 0.1)
        except Exception as e:
            print("WLAN-Start fehlgeschlagen:", e)
            self.ble.weiter()
            if self.quelle == "default" or not self.zugang():
                # Im Einrichtungsmodus ist der AP der einzige Zugang -
                # in 10 Sekunden noch einmal.
                self.ap_wunsch = True
                self.ap_naechster = time.monotonic() + 10.0

    def zugang(self):
        return self.taster is not None or bool(self.combo)

    def combo_pruefen(self, now):
        """True genau einmal, wenn die Kombination lange genug gehalten
        wurde. Danach erst wieder, wenn alle losgelassen waren."""
        if not self.combo:
            return False
        phys = self.ein.phys
        if all(phys[b] for b in self.combo):
            if self.combo_seit is None:
                self.combo_seit = now
            elif not self.combo_erledigt and now - self.combo_seit >= self.combo_halten:
                self.combo_erledigt = True
                return True
        else:
            self.combo_seit = None
            self.combo_erledigt = False
        return False

    def wlan_beenden(self):
        if self.rumble:
            self.rumble.not_aus()    # ohne Oberflaeche kein Handbetrieb mehr
        self._cal_speichern()
        self.suche.stoppen()
        self.web.beenden()
        self.cal_abort()
        self.ble.weiter()
        self.status_blinken(3)
        print("HID-Modus")

    def laufen(self):
        self.status_blinken(3)
        print("UniversalGC", VERSION, "-", self.c.get("name"),
              "- HID:", "ja" if self.hid else "NEIN", "- BLE:", self.ble.status())
        self.ap_wunsch = False
        self.ap_naechster = 0.0
        if self.quelle == "default":
            print("Keine device.json - Access Point startet von selbst")
            self.wlan_umschalten()
        elif not self.zugang():
            # Kein nutzbarer Konfigurationstaster (nicht eingetragen, oder der
            # Pinname passt nicht zum Board) und keine Tastenkombination -
            # dann ist der Access Point der einzige Weg an die Einstellungen.
            # Also gleich starten.
            print("Kein Konfigurationstaster - Access Point startet von selbst")
            self.wlan_umschalten()

        while True:
            now = time.monotonic()
            self.schritt(now)

            if self.taster is not None:
                e = self.taster.events.get()
                if e and e.pressed:
                    self.wlan_umschalten()
            if self.combo_pruefen(now):
                self.wlan_umschalten()

            if self.ap_wunsch and not self.web.aktiv and now >= self.ap_naechster:
                self.wlan_umschalten()

            if self.web.aktiv:
                self.web.bedienen()
                if self.web.stoppen:
                    self.wlan_beenden()
            else:
                time.sleep(0.001)

            if self.neustart_bei is not None and now >= self.neustart_bei:
                import microcontroller
                if self.rumble:
                    self.rumble.not_aus()
                    self.rumble.step()
                self.leds.aus()
                if self.nvm_beim_neustart or self.entwurf_beim_neustart:
                    if self.web.aktiv:
                        self.web.beenden()      # erst WLAN aus, dann Flash
                    for i, v in self.nvm_beim_neustart.items():
                        merker.setzen(i, v)
                    if self.entwurf_beim_neustart:
                        merker.entwurf_schreiben(self.entwurf_beim_neustart)
                microcontroller.reset()

            self.bestaetigen(now)


def entwurf_anwenden():
    """Eine im NVM wartende Belegung (siehe config_speichern) als device.json
    schreiben. Klappt das nicht, bleibt sie im NVM und gilt weiter -
    boot.py hat das Geraet ja schon mit ihr angemeldet."""
    if merker.lesen(merker.RUECKFALL) == merker.R_MAGIC:
        return          # erst den Rueckfall erledigen, Entwurf beim naechsten Start
    e = merker.entwurf_lesen()
    if not e:
        return
    try:
        if existiert(cfg.CONFIG_FILE):
            with open(cfg.CONFIG_FILE) as f:
                alt = f.read()
            with open(cfg.BACKUP_FILE, "w") as f:
                f.write(alt)
        with open(cfg.CONFIG_FILE, "w") as f:
            f.write(e)
        with open(cfg.PENDING_FILE, "w") as f:
            f.write("0")
    except OSError as ex:
        print("Neue Belegung wartet weiter im NVM:", ex)
        return
    merker.setzen(merker.FEHLSTARTS, 0)
    merker.entwurf_loeschen()
    print("Neue Belegung aus dem NVM gespeichert")


def rueckfall_anwenden():
    """boot.py hat wegen wiederholter Fehlstarts die Sicherung angemeldet.
    Sie wird jetzt wieder zur device.json - boot.py selbst darf nicht
    schreiben. Klappt das nicht (Wartungsmodus), bleibt der Merker stehen und
    der naechste Start versucht es erneut."""
    if merker.lesen(merker.RUECKFALL) != merker.R_MAGIC:
        return
    try:
        with open(cfg.BACKUP_FILE) as f:
            alt = f.read()
        with open(cfg.CONFIG_FILE, "w") as f:
            f.write(alt)
        if existiert(cfg.PENDING_FILE):
            os.remove(cfg.PENDING_FILE)
        merker.setzen(merker.RUECKFALL, 0)
        print("Alte Belegung zurueckgeholt")
    except OSError as e:
        print("Rueckfall noch nicht geschrieben:", e)


def start():
    try:
        entwurf_anwenden()
        rueckfall_anwenden()
        App().laufen()
    except Exception as e:
        import traceback
        try:
            text = "".join(traceback.format_exception(e))
        except Exception:
            text = repr(e)
        print(text)
        # Neue Belegung, die nicht laeuft: neu starten, boot.py zaehlt mit und
        # holt nach zwei Fehlstarts die alte Belegung zurueck.
        # Im Rueckfall nicht mehr: laeuft auch die alte Belegung nicht, wuerde
        # das Geraet sonst endlos neu starten.
        if (existiert(cfg.PENDING_FILE)
                and merker.lesen(merker.RUECKFALL) != merker.R_MAGIC):
            try:
                with open("/fehler.txt", "w") as f:
                    f.write(text)
            except OSError:
                pass
            time.sleep(1)
            import microcontroller
            microcontroller.reset()
        raise
