# SPDX-License-Identifier: GPL-3.0-or-later
# eingaben.py - Taster, Tastenmatrix, Schieberegister und Encoder
#
# Gelesen wird ueber das keypad-Modul von CircuitPython. Es tastet die Pins im
# Hintergrund ab (in C, nicht in Python), entprellt selbst und liefert nur
# Aenderungen. Das ist auf dem RP2040 und dem ESP32-S3 gleich.
#
# Jeder Button hat zwei Zustaende:
#   phys  was der Schalter gerade tut. Damit rechnet die Logik (b0, b1 ...).
#   aus   was an den PC geht. Unterscheidet sich je nach Betriebsart:
#           normal  wie phys
#           pulse   kurzer Impuls bei JEDER Aenderung - fuer Kippschalter,
#                   die im Spiel einen Tastendruck ausloesen sollen
#           toggle  jeder Druck schaltet um - ein Taster als Schalter
#
# Encoder erzeugen je Raste einen Impuls auf ihrem Rechts- oder Linksbutton.
# Statt eines Quadratur-Encoders (2 Pins) geht auch ein AS5600 hinter einem
# Drehknopf mit Rasten (1 Analogpin, beruehrungslos, prellt nicht).
# Schnelles Drehen wird gepuffert und nacheinander ausgegeben, damit das Spiel
# jede Raste mitbekommt.

try:
    import keypad
except ImportError:          # auf dem PC
    keypad = None


class Pulser:
    """Raststufen eines Encoders in Tastendruecke uebersetzen.

    Jeder Schritt wird zu einem Impuls von puls_s Sekunden, gefolgt von einer
    gleich langen Pause - ohne die Pause saehe das Spiel zwei Schritte in
    dieselbe Richtung als einen langen Druck.
    """

    MAX_STAU = 20            # mehr als das wird verworfen, sonst dreht es nach

    def __init__(self, puls_s=0.03):
        self.puls_s = puls_s
        self.stau = 0        # > 0 rechts, < 0 links
        self.an = 0          # 1 rechts gedrueckt, -1 links, 0 nichts
        self.bis = 0.0

    def dazu(self, schritte):
        if not schritte:
            return
        # Richtungswechsel verwirft den Rest der alten Richtung
        if (schritte > 0) != (self.stau > 0) and self.stau:
            self.stau = 0
        self.stau += schritte
        if self.stau > self.MAX_STAU:
            self.stau = self.MAX_STAU
        elif self.stau < -self.MAX_STAU:
            self.stau = -self.MAX_STAU

    def schritt(self, now):
        """Rueckgabe (rechts, links) als bool."""
        if now < self.bis:
            return self.an > 0, self.an < 0
        if self.an:
            # Impuls zu Ende, jetzt die Pause
            self.an = 0
            self.bis = now + self.puls_s
            return False, False
        if self.stau:
            self.an = 1 if self.stau > 0 else -1
            self.stau -= self.an
            self.bis = now + self.puls_s
        return self.an > 0, self.an < 0


class WinkelRaster:
    """Winkel eines AS5600 (0..65535 = eine Umdrehung) in Rasten zaehlen.

    Gezaehlt wird ab dem ersten Wert; der Knopf steht beim Start in einer
    Raste, also liegen alle Rasten bei ganzen Vielfachen von 360/rasten
    Grad davon. Eine Raste zaehlt erst, wenn der Winkel um hyst (Anteil einer
    Raste) ueber die Haelfte hinaus ist - so zappelt nichts, wenn der Knopf
    zwischen zwei Rasten steht. Der Nulldurchgang des Sensors stoert nicht,
    der Knopf darf sich endlos drehen.
    """

    def __init__(self, rasten=20, hyst=0.15):
        self.schritt = 65536.0 / max(2, int(rasten))
        self.hyst = hyst
        self.letzt = None
        self.s = 0.0           # Weg seit dem Start in Rohwerten
        self.k = 0             # gezaehlte Rasten

    def update(self, raw):
        if self.letzt is None:
            self.letzt = raw
            return self.k
        d = raw - self.letzt
        if d > 32767:
            d -= 65536
        elif d < -32768:
            d += 65536
        self.letzt = raw
        self.s += d
        x = self.s / self.schritt
        while x >= self.k + 0.5 + self.hyst:
            self.k += 1
        while x <= self.k - 0.5 - self.hyst:
            self.k -= 1
        return self.k


class WinkelEncoder:
    """AS5600 am Analogpin mit der Schnittstelle von rotaryio (position)."""

    def __init__(self, adc, rasten):
        import kalib
        self._mittel = kalib.kreis_mittel
        self.adc = adc
        self.raster = WinkelRaster(rasten)
        self._lesen()                  # Startwinkel = erste Raste

    def _lesen(self):
        a = self.adc
        return self.raster.update(self._mittel([a.value for _ in range(4)]))

    @property
    def position(self):
        return self._lesen()


class Modi:
    """Betriebsarten der Buttons: normal, pulse, toggle."""

    def __init__(self, n, puls_s=0.1):
        self.modus = {}          # bit -> "pulse" | "toggle"
        self.puls_s = puls_s
        self.puls_bis = {}
        self.latch = bytearray(n)

    def setzen(self, bit, modus):
        if modus in ("pulse", "toggle"):
            self.modus[bit] = modus

    def kante(self, bit, gedrueckt, now):
        m = self.modus.get(bit)
        if m == "pulse":
            self.puls_bis[bit] = now + self.puls_s
        elif m == "toggle" and gedrueckt:
            self.latch[bit] ^= 1

    def ausgabe(self, phys, aus, now):
        for bit, m in self.modus.items():
            if m == "toggle":
                aus[bit] = self.latch[bit]
            else:
                aus[bit] = 1 if now < self.puls_bis.get(bit, 0.0) else 0


class Eingaben:
    def __init__(self, c, bloecke, n_btn, pin):
        """pin(name) liefert das board-Objekt zum Pinnamen."""
        opt = c["options"]
        entprell = opt.get("debounce_ms", 20) / 1000.0
        self.n = n_btn
        self.phys = bytearray(n_btn)
        self.aus = bytearray(n_btn)
        self.modi = Modi(n_btn, opt.get("pulse_ms", 100) / 1000.0)
        self.scanner = []        # (keypad-Objekt, erstes Bit, invert-Liste)
        self.encoder = []        # (IncrementalEncoder, Pulser, bit_rechts, letzte)
        self.fehler = []

        # Direkte Taster - ein gemeinsamer Scanner fuer alle
        tb = c["buttons"]
        if tb:
            try:
                k = keypad.Keys([pin(b["pin"]) for b in tb],
                                value_when_pressed=False, pull=True,
                                interval=entprell)
                bits = [bloecke[("button", i)] for i in range(len(tb))]
                inv = [bool(b.get("invert")) for b in tb]
                self.scanner.append((k, bits, inv))
                for i, b in enumerate(tb):
                    self.modi.setzen(bits[i], b.get("mode", "normal"))
                    if inv[i]:
                        # Oeffner: ruhend "gedrueckt", keypad meldet nur
                        # Aenderungen - also Anfangszustand vorbelegen
                        self.phys[bits[i]] = 1
            except Exception as e:
                self.fehler.append("Taster: %s" % e)

        m = c.get("matrix")
        if m and m.get("rows") and m.get("cols"):
            try:
                k = keypad.KeyMatrix(
                    [pin(p) for p in m["rows"]], [pin(p) for p in m["cols"]],
                    columns_to_anodes=(m.get("diodes", "col2row") != "row2col"),
                    interval=entprell)
                erstes = bloecke[("matrix", 0)]
                n = len(m["rows"]) * len(m["cols"])
                self.scanner.append((k, [erstes + i for i in range(n)], None))
                for idx, modus in (m.get("modes") or {}).items():
                    self.modi.setzen(erstes + int(idx), modus)
            except Exception as e:
                self.fehler.append("Matrix: %s" % e)

        for i, s in enumerate(c["shift"]):
            try:
                n = int(s.get("count", 8))
                k = keypad.ShiftRegisterKeys(
                    clock=pin(s["clock"]), data=pin(s["data"]),
                    latch=pin(s["latch"]), key_count=n,
                    value_when_pressed=bool(s.get("active_high", False)),
                    interval=entprell)
                erstes = bloecke[("shift", i)]
                self.scanner.append((k, [erstes + j for j in range(n)], None))
                for idx, modus in (s.get("modes") or {}).items():
                    self.modi.setzen(erstes + int(idx), modus)
            except Exception as e:
                self.fehler.append("Schieberegister %d: %s" % (i + 1, e))

        for i, e in enumerate(c["encoders"]):
            try:
                if e.get("type") == "as5600":
                    import analogio
                    enc = WinkelEncoder(analogio.AnalogIn(pin(e["pin"])),
                                        int(e.get("detents", 20)))
                else:
                    import rotaryio
                    enc = rotaryio.IncrementalEncoder(pin(e["a"]), pin(e["b"]),
                                                      divisor=int(e.get("divisor", 4)))
                p = Pulser(e.get("pulse_ms", 30) / 1000.0)
                bit = bloecke[("encoder", i)]
                self.encoder.append([enc, p, bit, enc.position,
                                     -1 if e.get("reverse") else 1])
            except Exception as ex:
                self.fehler.append("Encoder %d: %s" % (i + 1, ex))

    def update(self, now):
        for k, bits, inv in self.scanner:
            ev = k.events
            if ev.overflowed:
                # Zu viele Ereignisse verpasst: alles neu einlesen. reset()
                # meldet danach jeden gedrueckten Button erneut.
                ev.clear()
                for b in bits:
                    self.phys[b] = 1 if (inv and inv[bits.index(b)]) else 0
                k.reset()
            e = ev.get()
            while e:
                i = e.key_number
                if i < len(bits):
                    an = e.pressed
                    if inv is not None and inv[i]:
                        an = not an
                    b = bits[i]
                    if self.phys[b] != (1 if an else 0):
                        self.phys[b] = 1 if an else 0
                        self.modi.kante(b, an, now)
                e = ev.get()

        self.aus[:] = self.phys
        self.modi.ausgabe(self.phys, self.aus, now)

        for eintrag in self.encoder:
            enc, p, bit, letzte, richtung = eintrag
            pos = enc.position
            if pos != letzte:
                p.dazu((pos - letzte) * richtung)
                eintrag[3] = pos
            r, l = p.schritt(now)
            self.phys[bit] = self.aus[bit] = 1 if r else 0
            self.phys[bit + 1] = self.aus[bit + 1] = 1 if l else 0

    def encoder_positionen(self):
        return [e[0].position * e[4] for e in self.encoder]
