# rumble.py - Vibrationsmotoren an DRV8871 (aus den Pedalen v9.7)
#
# Angesteuert im "slow decay"-Verfahren: IN1 liegt fest an, IN2 bekommt die
# INVERTIERTE PWM. Zwischen den Impulsen wird die Wicklung kurzgeschlossen
# statt geoeffnet, das Drehmoment bei kleinem Duty ist viel hoeher. Am realen
# Aufbau gemessen sinkt die Abfallschwelle damit von 60 auf 6 Prozent.
#
# Voraussetzung: IN1 und IN2 eines Kanals auf derselben PWM-Einheit des
# RP2040 - erster Pin gerade, zweiter direkt danach (GP4/GP5, GP6/GP7 ...).
#
# Die Effekte rechnet das Geraet NICHT selbst: SimHubs ShakeIt-Motoren
# exportieren ihren Ausgangswert, und der kommt ueber die Telemetrie hierher.
#
# device.json:
#   "rumble": {"channels": [{"in1": "GP4", "in2": "GP5", "name": "Bremse",
#                            "tele": "bremse"}],
#              "supply": 15.0, "motor": 12.0, "pwm_hz": 20000,
#              "kick_ms": 50, "brake_ms": 80, "tele_max": 100}
# Die Feineinstellung je Kanal (Schwelle, min, max ...) steht in rumble.json
# und wird ueber die Weboberflaeche gesetzt.

import json
import time

try:
    import pwmio
except ImportError:
    pwmio = None

DATEI = "/rumble.json"
VOLL = 65535
TEST_TTL = 1.2      # Totmannschaltung fuer den Handbetrieb aus dem Browser


class Rumble:
    def __init__(self, rcfg, pin):
        rcfg = rcfg or {}
        self.kanaele = rcfg.get("channels", [])
        self.n = len(self.kanaele)
        self.hz = rcfg.get("pwm_hz", 20000)
        self.kick_s = rcfg.get("kick_ms", 50) / 1000
        self.brems_s = rcfg.get("brake_ms", 80) / 1000
        self.verzug_ms = rcfg.get("brake_delay_ms", 0)
        self.tele_max = rcfg.get("tele_max", 100.0) or 1.0
        vers = rcfg.get("supply", 12.0) or 12.0
        nenn = rcfg.get("motor", 12.0) or 12.0
        # Deckel, damit ein 12-V-Motor an hoeherer Versorgung im Mittel nur
        # seine Nennspannung sieht. Der Kickstart darf bewusst darueber.
        self.deckel = min(VOLL, int(VOLL * nenn / vers))

        self.in1 = []
        self.in2 = []
        self.fehler = []
        for k in self.kanaele:
            try:
                a = pwmio.PWMOut(pin(k["in1"]), frequency=self.hz, duty_cycle=0)
                b = pwmio.PWMOut(pin(k["in2"]), frequency=self.hz, duty_cycle=0)
                self.in1.append(a)
                self.in2.append(b)
                p1, p2 = k["in1"], k["in2"]
                if p1[:2] == "GP" and p2[:2] == "GP":
                    if not (int(p1[2:]) % 2 == 0 and int(p2[2:]) == int(p1[2:]) + 1):
                        print("Rumble: %s/%s nicht auf derselben PWM-Einheit" % (p1, p2))
            except Exception as e:
                self.fehler.append("Rumble %s: %s" % (k.get("name", "?"), e))
                self.in1.append(None)
                self.in2.append(None)
        self.da = any(x is not None for x in self.in1)

        n = self.n
        self.soll = [0.0] * n
        self.ist = [0.0] * n
        self.phase = ["aus"] * n        # aus | kick | lauf | leer | brems
        self.bis = [0.0] * n
        self.test = [None] * n
        self.test_bis = [0.0] * n
        self.seq = -1
        self.sperre = 0.0
        self.cfg = self.laden()

    # --- Einstellungen ---

    def vorgabe(self):
        return [{"schwelle": 4, "min": 8, "max": 100, "kick": 12, "gain": 100,
                 "brems": self.verzug_ms, "an": True} for _ in range(self.n)]

    def laden(self):
        cfg = self.vorgabe()
        try:
            with open(DATEI) as f:
                d = json.load(f)
            for i in range(self.n):
                if i < len(d) and isinstance(d[i], dict):
                    cfg[i].update(d[i])
        except (OSError, ValueError):
            pass
        return cfg

    def speichern(self):
        try:
            with open(DATEI, "w") as f:
                json.dump(self.cfg, f)
            return True
        except OSError as e:
            print("Rumble-Einstellungen nicht speicherbar:", e)
            return False

    def setzen(self, liste):
        for i in range(self.n):
            if i < len(liste) and isinstance(liste[i], dict):
                for feld in ("schwelle", "min", "max", "kick", "gain", "brems"):
                    if feld in liste[i]:
                        v = int(liste[i][feld])
                        grenze = 1000 if feld == "brems" else 200
                        self.cfg[i][feld] = 0 if v < 0 else min(v, grenze)
                if "an" in liste[i]:
                    self.cfg[i]["an"] = bool(liste[i]["an"])
        return self.speichern()

    # --- Ansteuerung ---

    def _roh(self, k, duty):
        if self.in1[k] is None:
            return
        duty = 0 if duty < 0 else min(duty, VOLL)
        self.in1[k].duty_cycle = VOLL
        self.in2[k].duty_cycle = VOLL - duty

    def _frei(self, k):
        if self.in1[k] is not None:
            self.in1[k].duty_cycle = 0
            self.in2[k].duty_cycle = 0

    def _bremsen(self, k):
        if self.in1[k] is not None:
            self.in1[k].duty_cycle = VOLL
            self.in2[k].duty_cycle = VOLL

    @staticmethod
    def schwelle(c, e):
        """Schwelle anwenden und den Rest auf 0..1 spreizen (wie SimHubs
        Threshold) - sonst brummt der Motor bei jedem Hintergrundrauschen."""
        s = c.get("schwelle", 0) / 100.0
        if s <= 0.0:
            return e
        if e <= s:
            return 0.0
        if s >= 1.0:
            return 1.0
        return (e - s) / (1.0 - s)

    def duty(self, k, e):
        c = self.cfg[k]
        p = c["min"] + e * (c["max"] - c["min"])
        p = 0 if p < 0 else min(p, 100)
        return int(self.deckel * p / 100)

    def test_setzen(self, k, v, seq=None):
        """Handbetrieb, v in Prozent, negativ beendet. seq verwirft
        ueberholte Anforderungen eines Schiebereglers (Pedale v9.7)."""
        if k < 0 or k >= self.n or time.monotonic() < self.sperre:
            return
        if seq is not None:
            if seq <= self.seq:
                return
            self.seq = seq
        if v is None or v < 0:
            self.test[k] = None
            self.test_bis[k] = 0.0
        else:
            self.test[k] = min(1.0, v / 100.0)
            self.test_bis[k] = time.monotonic() + TEST_TTL

    def alles_aus(self):
        for k in range(self.n):
            self.soll[k] = 0.0
            self.test[k] = None
            self.test_bis[k] = 0.0

    def not_aus(self):
        """Alles aus und zwei Sekunden nichts annehmen, damit keine noch
        wartende Anforderung den Motor wieder anwirft."""
        self.sperre = time.monotonic() + 2.0
        self.alles_aus()

    def telemetrie(self, werte):
        if not werte:
            return
        for k, kanal in enumerate(self.kanaele):
            v = werte.get(str(kanal.get("tele", "")).lower())
            if isinstance(v, (int, float)):
                e = v / self.tele_max * self.cfg[k].get("gain", 100) / 100.0
                self.soll[k] = 0.0 if e < 0 else min(e, 1.0)

    def step(self):
        """Jede Runde aufrufen, blockiert nie."""
        if not self.da:
            return
        now = time.monotonic()
        for k in range(self.n):
            if self.in1[k] is None:
                continue
            if self.test[k] is not None and now > self.test_bis[k]:
                self.test[k] = None
            c = self.cfg[k]
            e = self.soll[k] if self.test[k] is None else self.test[k]
            if not c.get("an", True):
                e = 0.0
            e = self.schwelle(c, e)
            self.ist[k] = e
            ph = self.phase[k]

            if e <= 0.004:
                # "brems" ist ein Charakterregler: 0 ms stoppt jeden Impuls
                # sofort (ABS, Randstein), hoch laesst Luecken auslaufen
                # (Fahrbahn, Radschlupf).
                if ph in ("kick", "lauf"):
                    self._frei(k)
                    self.phase[k] = "leer"
                    self.bis[k] = now + c.get("brems", self.verzug_ms) / 1000
                elif ph == "leer" and now >= self.bis[k]:
                    self._bremsen(k)
                    self.phase[k] = "brems"
                    self.bis[k] = now + self.brems_s
                elif ph == "brems" and now >= self.bis[k]:
                    self._frei(k)
                    self.phase[k] = "aus"
                continue

            if ph == "leer":
                self._roh(k, self.duty(k, e))      # dreht noch, kein Kick
                self.phase[k] = "lauf"
            elif ph in ("aus", "brems"):
                ziel = c["min"] + e * (c["max"] - c["min"])
                if ziel < c.get("kick", 0):
                    self._roh(k, VOLL)
                    self.phase[k] = "kick"
                    self.bis[k] = now + self.kick_s
                else:
                    self._roh(k, self.duty(k, e))
                    self.phase[k] = "lauf"
            elif ph == "kick":
                if now >= self.bis[k]:
                    self._roh(k, self.duty(k, e))
                    self.phase[k] = "lauf"
            else:
                self._roh(k, self.duty(k, e))
