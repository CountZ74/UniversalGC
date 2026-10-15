# SPDX-License-Identifier: GPL-3.0-or-later
# suche.py - Pin-Suche: herausfinden, was an welchem Pin haengt
#
# Ein Pin verraet von selbst nicht, was an ihm haengt - ein nicht gedrueckter
# Taster ist elektrisch dasselbe wie ein leerer Pin. Deshalb ein Lernmodus:
# alle freien Pins werden beobachtet, und man bewegt nacheinander seine
# Bedienelemente.
#
#   Modus "d" (digital)  alle freien Pins als Eingang mit Pull-up.
#                        Taster:  Pin geht auf GND.
#                        Encoder: zwei Pins schalten abwechselnd und schnell.
#   Modus "a" (analog)   alle freien Analogpins werden gemessen.
#                        Poti/Hall: der Wert bewegt sich deutlich ueber das
#                        Grundrauschen hinaus.
#
# SICHERHEIT: Es werden nur Eingaenge geschaltet, nie Ausgaenge - an einem
# Motortreiber oder einem Taster gegen GND koennte ein Ausgang Schaden
# anrichten. Belegte, reservierte und Strapping-Pins bleiben unangetastet.
#
# Die Auswertung (Klasse Auswertung) kommt ohne Hardware aus und wird auf dem
# PC getestet.

import time

# Strapping-Pins: ein Pegel beim Einschalten bestimmt den Startmodus des Chips.
# Ein gedrueckter Taster dort kann den naechsten Start verstellen - fuer die
# Suche tabu. (ESP32-S3: GPIO0, 3, 45, 46.)
STRAPPING = {"esp32s3": (0, 3, 45, 46)}

ENC_FENSTER = 1.5        # s, in denen ein Encoder mehrfach schalten muss
ENC_MIN_FLANKEN = 4      # Flanken je Pin im Fenster
LAUFZEIT = 300.0         # s, danach endet die Suche von selbst


class Auswertung:
    """Ereignisse sammeln und Vorschlaege daraus ableiten. Ohne Hardware."""

    def __init__(self, namen):
        self.namen = list(namen)
        n = len(self.namen)
        self.gedrueckt = [False] * n      # aktueller Zustand
        self.druecke = [0] * n            # Zahl der Druecke
        self.seit = [0.0] * n             # Zeitpunkt der letzten Aenderung
        self.flanken = [[] for _ in range(n)]
        self.enc_fest = []                # einmal erkannte Encoder-Paare

    def ereignis(self, i, gedrueckt, t):
        if i < 0 or i >= len(self.namen):
            return
        if gedrueckt and not self.gedrueckt[i]:
            self.druecke[i] += 1
        self.gedrueckt[i] = gedrueckt
        self.seit[i] = t
        f = self.flanken[i]
        f.append(t)
        if len(f) > 16:
            del f[0]
        # Gleich hier pruefen, solange die Flanken frisch sind - wer erst
        # Sekunden spaeter auf die Liste schaut, soll den Encoder noch sehen.
        if len(f) >= ENC_MIN_FLANKEN:
            self._encoder_suchen(t)

    def _frisch(self, i, now):
        return [t for t in self.flanken[i] if now - t <= ENC_FENSTER]

    def encoder(self, now):
        """Alle bisher erkannten Encoder-Paare (i, j) mit i < j."""
        self._encoder_suchen(now)
        return list(self.enc_fest)

    def _encoder_suchen(self, now):
        """Pin-Paare, die wie ein Encoder schalten: beide oft und
        abwechselnd. Gefundene Paare bleiben gemerkt."""
        aktiv = [i for i in range(len(self.namen))
                 if len(self._frisch(i, now)) >= ENC_MIN_FLANKEN]
        paare = self.enc_fest
        benutzt = set()
        for i, j in paare:
            benutzt.add(i)
            benutzt.add(j)
        for a in range(len(aktiv)):
            for b in range(a + 1, len(aktiv)):
                i, j = aktiv[a], aktiv[b]
                if i in benutzt or j in benutzt:
                    continue
                fi, fj = self._frisch(i, now), self._frisch(j, now)
                # gemeinsam sortieren und zaehlen, wie oft der Pin wechselt
                folge = sorted([(t, 0) for t in fi] + [(t, 1) for t in fj])
                wechsel = sum(1 for k in range(1, len(folge))
                              if folge[k][1] != folge[k - 1][1])
                if wechsel >= 3 and abs(len(fi) - len(fj)) <= 3:
                    paare.append((i, j))
                    benutzt.add(i)
                    benutzt.add(j)

    def vorschlaege(self, now):
        """Liste von dicts fuer die Weboberflaeche, neueste zuerst."""
        enc = self.encoder(now)
        in_enc = set()
        out = []
        for i, j in enc:
            in_enc.add(i)
            in_enc.add(j)
            out.append({"art": "encoder", "a": self.namen[i], "b": self.namen[j],
                        "t": round(now - max(self.seit[i], self.seit[j]), 1)})
        for i, n in enumerate(self.namen):
            if i in in_enc or not self.druecke[i]:
                continue
            # Laenger als 2 s gedrueckt: vermutlich ein Kippschalter
            gehalten = self.gedrueckt[i] and now - self.seit[i] > 2.0
            out.append({"art": "schalter" if gehalten else "taster",
                        "a": n, "z": self.druecke[i], "an": self.gedrueckt[i],
                        "t": round(now - self.seit[i], 1)})
        out.sort(key=lambda e: e["t"])
        return out


class AnalogAuswertung:
    """Analogpins: Grundrauschen in der ersten Sekunde lernen, danach melden,
    wo sich der Wert deutlich darueber hinaus bewegt."""

    LERNZEIT = 1.0
    MIN_WEG = 0.15            # Anteil von 65535, ab dem es eine Achse ist

    def __init__(self, namen, start):
        self.namen = list(namen)
        n = len(self.namen)
        self.start = start
        self.rausch_min = [65535] * n
        self.rausch_max = [0] * n
        self.mn = [65535] * n
        self.mx = [0] * n
        self.wert = [0] * n

    def messung(self, i, v, now):
        self.wert[i] = v
        if now - self.start < self.LERNZEIT:
            self.rausch_min[i] = min(self.rausch_min[i], v)
            self.rausch_max[i] = max(self.rausch_max[i], v)
            self.mn[i] = self.mx[i] = v
            return
        self.mn[i] = min(self.mn[i], v)
        self.mx[i] = max(self.mx[i], v)

    def vorschlaege(self):
        out = []
        for i, n in enumerate(self.namen):
            weg = self.mx[i] - self.mn[i]
            rausch = max(0, self.rausch_max[i] - self.rausch_min[i])
            if weg >= self.MIN_WEG * 65535 and weg > 4 * rausch:
                out.append({"art": "achse", "a": n, "v": self.wert[i],
                            "min": self.mn[i], "max": self.mx[i],
                            "r": rausch})
        out.sort(key=lambda e: -(e["max"] - e["min"]))
        return out


class PinSuche:
    """Hardware-Teil: Pins oeffnen, abfragen, wieder freigeben."""

    def __init__(self, app):
        self.app = app
        self.modus = None
        self.keys = None
        self.adcs = []
        self.ausw = None
        self.ende = 0.0
        self.namen = []
        self.fehler = []

    def freie_pins(self, analog):
        """Board-Namen aller Pins, die gefahrlos beobachtet werden koennen."""
        import cfg
        p = self.app.pins
        belegt = set()
        for name, _ in cfg.pins_belegt(self.app.c):
            k = p.pin_id(name)
            if k:
                belegt.add(k)
        tabu = STRAPPING.get(p.chip, ())
        out = []
        for e in p.json():
            if e["r"] or e["nr"] is None or e["nr"] in tabu:
                continue
            if analog and not e["a"]:
                continue
            if p.pin_id(e["n"]) in belegt:
                continue
            out.append(e["n"])
        return out

    def starten(self, modus):
        self.stoppen()
        now = time.monotonic()
        self.modus = modus
        self.fehler = []
        self.ende = now + LAUFZEIT
        if modus == "a":
            import analogio
            namen = []
            for n in self.freie_pins(True):
                try:
                    self.adcs.append(analogio.AnalogIn(self.app.pins.objekt(n)))
                    namen.append(n)
                except Exception as e:
                    self.fehler.append("%s: %s" % (n, e))
            self.namen = namen
            self.ausw = AnalogAuswertung(namen, now)
        else:
            import keypad
            namen = []
            objs = []
            for n in self.freie_pins(False):
                try:
                    objs.append(self.app.pins.objekt(n))
                    namen.append(n)
                except Exception as e:
                    self.fehler.append("%s: %s" % (n, e))
            self.namen = namen
            self.ausw = Auswertung(namen)
            if objs:
                try:
                    # Kurzes Intervall, damit auch Encoder-Flanken ankommen
                    self.keys = keypad.Keys(objs, value_when_pressed=False,
                                            pull=True, interval=0.003,
                                            max_events=128)
                except Exception as e:
                    self.fehler.append(str(e))
                    self.keys = None

    def stoppen(self):
        if self.keys is not None:
            try:
                self.keys.deinit()
            except Exception:
                pass
        for a in self.adcs:
            try:
                a.deinit()
            except Exception:
                pass
        self.keys = None
        self.adcs = []
        self.modus = None

    def schritt(self, now):
        if self.modus is None:
            return
        if now > self.ende:
            self.stoppen()
            return
        if self.keys is not None:
            ev = self.keys.events
            if ev.overflowed:
                ev.clear()
            e = ev.get()
            while e:
                self.ausw.ereignis(e.key_number, e.pressed, now)
                e = ev.get()
        for i, a in enumerate(self.adcs):
            self.ausw.messung(i, a.value, now)

    def json(self):
        now = time.monotonic()
        if self.modus is None:
            return {"m": None}
        return {"m": self.modus, "n": len(self.namen),
                "rest": int(self.ende - now), "f": self.fehler,
                "v": (self.ausw.vorschlaege() if self.modus == "a"
                      else self.ausw.vorschlaege(now))}
