# SPDX-License-Identifier: GPL-3.0-or-later
# kalib.py - Kalibrierung und Kennlinien aller Achsen
#
# Keine Hardware-Importe - die Tests laufen auf dem PC.
#
# Pro Achse wird gespeichert (calibration.json, Liste in Achsreihenfolge):
#   typ    "pot"     lineare Groesse 0..65535 (Poti, Hall-Sensor, Paddle)
#          "as5600"  Kreisgroesse 0..65535, entspricht 0..360 Grad. Darf den
#                    Nulldurchgang beliebig oft ueberqueren (Pedale v9).
#          "hx711"   Waegezelle, 0 = kein Druck (tariert)
#   start  Rohwert in Ruhestellung
#   span   Weg in Rohwerten, VORZEICHENBEHAFTET: > 0 Rohwert steigt beim
#          Betaetigen, < 0 er faellt. Ein Vorzeichenwechsel kehrt die Achse um.
#   curve  Stuetzpunkte der Kennlinie in Prozent
#
# Totzone am Anfang und Reserve am Ende stehen in device.json je Achse
# ("deadzone", "margin" in Prozent) und wirken bei der Auswertung - eine
# Aenderung braucht also keine neue Kalibrierung.

ADC_SPAN  = 65536
HALF_SPAN = ADC_SPAN // 2
AXIS_MAX  = 65535

DEFAULT_CURVE = [[0, 0], [25, 25], [50, 50], [75, 75], [100, 100]]

# Vorgaben je Typ: (Totzone %, Reserve %)
RAENDER = {"pot": (1.0, 1.0), "as5600": (1.5, 2.0), "hx711": (1.5, 2.0),
           "encoder": (0.0, 0.0)}

MIN_SPAN = {"pot": 500, "as5600": 300, "hx711": 1000}

# Sweep-Abdeckungskarte fuer den AS5600: 256 Felder zu je 1,4 Grad
SWEEP_FELDER = 256
SWEEP_SHIFT  = 8
SWEEP_BREITE = ADC_SPAN // SWEEP_FELDER
# Groesster Sprung zwischen zwei Messungen, der noch als durchgehende
# Bewegung aufgefuellt wird: 64 Felder = 90 Grad (siehe Pedale v9.4).
SWEEP_FUELL_MAX = 64


def neue_kurve():
    return [list(p) for p in DEFAULT_CURVE]


def cal_default(typ, hx_max=50000):
    if typ == "hx711":
        return {"typ": typ, "start": 0, "span": hx_max, "curve": neue_kurve()}
    return {"typ": typ, "start": 0, "span": ADC_SPAN - 1, "curve": neue_kurve()}


def cal_passend(alt, typ, hx_max=50000):
    """Gespeicherten Datensatz uebernehmen, wenn er zum Achstyp passt."""
    if not isinstance(alt, dict) or alt.get("typ") != typ:
        return cal_default(typ, hx_max)
    c = cal_default(typ, hx_max)
    c.update(alt)
    if not isinstance(c.get("curve"), list) or len(c["curve"]) < 2:
        c["curve"] = neue_kurve()
    if typ == "hx711":
        c["start"] = 0
        if c["span"] <= 0:
            c["span"] = hx_max
    return c


def raender(achse_cfg):
    t = achse_cfg.get("type", "pot")
    dz, mg = RAENDER.get(t, (1.0, 1.0))
    dz = float(achse_cfg.get("deadzone", dz)) / 100.0
    mg = float(achse_cfg.get("margin", mg)) / 100.0
    if dz < 0:
        dz = 0.0
    if mg < 0:
        mg = 0.0
    if dz + mg > 0.9:
        dz, mg = 0.0, 0.0
    return dz, mg


def roh_norm(raw, c):
    """Rohwert -> 0.0 .. 1.0 ohne Totzone, wraparound-fest beim AS5600."""
    span = c["span"]
    if span == 0:
        return 0.0
    t = c.get("typ")
    if t == "hx711":
        return raw / span if span > 0 else 0.0
    if t == "as5600":
        # Der genutzte Bogen laeuft von start ueber span. Im ungenutzten Rest
        # des Kreises entscheidet die kuerzere Distanz: naeher am Start ->
        # losgelassen, naeher am Ende -> durchgetreten. So kippt ein
        # zitternder Sensor an der 0-Grad-Grenze nicht von 0 auf 100 Prozent.
        start = c["start"]
        if span > 0:
            d = (raw - start) % ADC_SPAN
            s = span
        else:
            d = (start - raw) % ADC_SPAN
            s = -span
        if d <= s:
            return d / s
        if (ADC_SPAN - d) <= (d - s):
            return 0.0
        return 1.0
    return (raw - c["start"]) / span


def norm(raw, c, dz=0.0, mg=0.0):
    """Rohwert -> 0.0 .. 1.0 mit Totzone am Anfang und Reserve am Ende."""
    n = roh_norm(raw, c)
    if n <= dz:
        return 0.0
    if n >= 1.0 - mg:
        return 1.0
    return (n - dz) / (1.0 - dz - mg)


def kurve(x, punkte):
    """Prozent -> Prozent, linear zwischen den Stuetzpunkten."""
    x = 0 if x < 0 else (100 if x > 100 else x)
    if not punkte or len(punkte) < 2:
        return x
    if x <= punkte[0][0]:
        return punkte[0][1]
    if x >= punkte[-1][0]:
        return punkte[-1][1]
    for i in range(len(punkte) - 1):
        x0, y0 = punkte[i]
        x1, y1 = punkte[i + 1]
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0) if x1 != x0 else 0
            return y0 + t * (y1 - y0)
    return x


def ausgabe(n, c):
    """0..1 nach Kalibrierung -> HID-Wert 0..65535 nach Kennlinie."""
    p = kurve(n * 100, c.get("curve", DEFAULT_CURVE))
    p = 0.0 if p < 0 else (100.0 if p > 100 else p)
    v = int(p / 100.0 * AXIS_MAX + 0.5)
    return 0 if v < 0 else (AXIS_MAX if v > AXIS_MAX else v)


def kreis_mittel(samples):
    """Mittelwert einer Kreisgroesse.

    Liegen die Samples um den Nulldurchgang herum (65500 und 30), waere das
    einfache Mittel 32765 - genau gegenueber. Deshalb wird um das erste Sample
    herum entfaltet, gemittelt und wieder zurueckgeklappt.
    """
    basis = samples[0]
    summe = 0
    for s in samples[1:]:
        d = (s - basis) % ADC_SPAN
        if d > HALF_SPAN:
            d -= ADC_SPAN
        summe += d
    return (basis + summe // len(samples)) % ADC_SPAN


def flip(c):
    """Richtung umkehren ohne neue Kalibrierung: Ende wird zum Start."""
    if c.get("typ") == "hx711" or not c["span"]:
        return
    if c.get("typ") == "as5600":
        c["start"] = (c["start"] + c["span"]) % ADC_SPAN
    else:
        c["start"] = c["start"] + c["span"]
    c["span"] = -c["span"]


class Sweep:
    """Wegmessung fuer eine Achse: Ruhestellung setzen, dann ein paar Mal
    voll durchbewegen. Weg und Richtung ergeben sich daraus.

    pot     Minimum und Maximum werden mitgeschrieben. Das Ende, das naeher an
            der Ruhestellung liegt, wird 0 Prozent.
    as5600  Abdeckungskarte (Pedale v9.3): angekreuzt wird, WO die Achse war,
            nicht wie weit sie lief. Eine Messpause laesst hoechstens ein Feld
            leer, das der naechste Durchgang wieder fuellt.
            Fuer den Weg zaehlen nicht nur ganze Felder: je Feld wird der
            kleinste und groesste tatsaechlich gemessene Wert gemerkt, damit
            Start und Ende auf den Rohwert genau stimmen. Ganze Felder allein
            lagen bis zu 256 Rohwerte (1,4 Grad) daneben - bei kurzem
            Pedalweg erreichte das Pedal dann nur rund 97 Prozent.
    hx711   groesste Kraft.
    """

    def __init__(self, typ, null):
        self.typ = typ
        self.null = null
        self.mn = null
        self.mx = null
        self.cover = None
        if typ == "as5600":
            self.cover = bytearray(SWEEP_FELDER)
            # kleinster/groesster gemessener Wert innerhalb jedes Feldes
            # (untere 8 bit); -1/256 = dort nie gemessen
            self.fmin = [256] * SWEEP_FELDER
            self.fmax = [-1] * SWEEP_FELDER
            self.feld = null >> SWEEP_SHIFT
            self.cover[self.feld] = 1
            self._merken(null)

    def _merken(self, raw):
        f = raw >> SWEEP_SHIFT
        r = raw & (SWEEP_BREITE - 1)
        if r < self.fmin[f]:
            self.fmin[f] = r
        if r > self.fmax[f]:
            self.fmax[f] = r

    def _durchlaufen(self, i):
        """Feld zwischen zwei Messungen: ganz ueberstrichen."""
        self.cover[i] = 1
        self.fmin[i] = 0
        self.fmax[i] = SWEEP_BREITE - 1

    def update(self, raw):
        if self.typ != "as5600":
            if raw < self.mn:
                self.mn = raw
            if raw > self.mx:
                self.mx = raw
            return
        feld = raw >> SWEEP_SHIFT
        d = (feld - self.feld) % SWEEP_FELDER
        if d == 0:
            self._merken(raw)
            return
        if d <= SWEEP_FUELL_MAX:                     # aufwaerts, Strecke fuellen
            i = self.feld
            for _ in range(d - 1):
                i = (i + 1) % SWEEP_FELDER
                self._durchlaufen(i)
        elif SWEEP_FELDER - d <= SWEEP_FUELL_MAX:    # abwaerts
            i = self.feld
            for _ in range(SWEEP_FELDER - d - 1):
                i = (i - 1) % SWEEP_FELDER
                self._durchlaufen(i)
        self.cover[feld] = 1                         # Endpunkt: echte Messung
        self._merken(raw)
        self.feld = feld

    def wege(self):
        """(aufwaerts, abwaerts) in Rohzaehlern ab der Ruhestellung."""
        if self.typ == "hx711":
            return self.mx, 0
        if self.typ == "pot":
            return self.mx - self.null, self.null - self.mn
        null = self.null >> SWEEP_SHIFT
        vor = 0
        i = null
        while vor < SWEEP_FELDER - 1:
            i = (i + 1) % SWEEP_FELDER
            if not self.cover[i]:
                break
            vor += 1
        rueck = 0
        i = null
        while rueck < SWEEP_FELDER - 1:
            i = (i - 1) % SWEEP_FELDER
            if not self.cover[i]:
                break
            rueck += 1
        # Auf den Rohwert genau: vom Nullpunkt bis zum aeussersten gemessenen
        # Wert im letzten Feld der Strecke
        rest = self.null & (SWEEP_BREITE - 1)
        ende = (null + vor) % SWEEP_FELDER
        fmax = self.fmax[ende] if self.fmax[ende] >= 0 else SWEEP_BREITE - 1
        auf = max(0, vor * SWEEP_BREITE + fmax - rest)
        ende = (null - rueck) % SWEEP_FELDER
        fmin = self.fmin[ende] if self.fmin[ende] < SWEEP_BREITE else 0
        ab = max(0, rueck * SWEEP_BREITE + rest - fmin)
        return auf, ab

    def weg(self):
        a, b = self.wege()
        if self.typ == "pot":
            return a + b
        return a if a >= b else b

    def ergebnis(self):
        """(start, span) oder None, wenn zu wenig Bewegung erkannt wurde."""
        if self.weg() < MIN_SPAN.get(self.typ, 300):
            return None
        if self.typ == "hx711":
            return 0, self.mx
        if self.typ == "pot":
            weite = self.mx - self.mn
            # Ruhestellung naeher am Minimum -> Rohwert steigt beim Betaetigen
            if (self.null - self.mn) <= (self.mx - self.null):
                return self.mn, weite
            return self.mx, -weite
        auf, ab = self.wege()
        if auf >= ab:
            return self.null, auf
        return self.null, -ab
