# SPDX-License-Identifier: GPL-3.0-or-later
# leds.py - einfache LEDs und WS2812-Streifen
#
# Einfache LEDs (aus der Buttonbox): jede LED hat zwei Logikausdruecke.
#   on     wahr -> Dauerlicht
#   blink  wahr -> blinkt (Dauerlicht hat Vorrang)
# Beispiel Anlasser-LED: on = "motor", blink = "AND(b9,b10)".
#
# WS2812 (Neopixel): ein Drehzahlband fuer den Schaltblitz plus Regeln, die
# einzelne LEDs per Logikausdruck einfaerben (z.B. Pit-Limiter, DRS, Flaggen).
# Die Regeln haben Vorrang vor dem Drehzahlband, spaetere vor frueheren.
#
# Die Ausdruecke stehen in logic.json und lassen sich in der Weboberflaeche
# ohne Neustart aendern. Die Pins stehen in device.json.

import logik

try:
    import digitalio
except ImportError:
    digitalio = None


def farbe(text, standard=(0, 0, 0)):
    """'#ff8000' -> (255, 128, 0)."""
    try:
        t = str(text).lstrip("#")
        return (int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))
    except (ValueError, IndexError):
        return standard


def bereich(text, n):
    """'0-3,7' -> [0, 1, 2, 3, 7], nur gueltige Indizes."""
    out = []
    for teil in str(text).replace(" ", "").split(","):
        if not teil:
            continue
        try:
            if "-" in teil:
                a, b = teil.split("-", 1)
                out.extend(range(int(a), int(b) + 1))
            else:
                out.append(int(teil))
        except ValueError:
            pass
    return [i for i in out if 0 <= i < n]


def drehzahlband(anteil, n, start, blitz, farben):
    """Farben fuer ein Drehzahlband aus n LEDs.

    anteil  aktuelle Drehzahl, 0..1 (1 = Begrenzer)
    start   ab hier leuchtet die erste LED (0..1)
    blitz   ab hier blinkt alles (0..1), None = nie
    farben  Liste von Farben, gleichmaessig ueber das Band verteilt

    Rueckgabe: (liste_von_farben_oder_None, blitzen)
    """
    if blitz is not None and anteil >= blitz:
        return None, True
    out = [(0, 0, 0)] * n
    if n == 0 or anteil <= start:
        return out, False
    an = int((anteil - start) / (1.0 - start) * n + 0.5) if start < 1 else n
    an = min(an, n)
    for i in range(an):
        fi = i * len(farben) // n if farben else 0
        out[i] = farben[fi] if farben else (0, 255, 0)
    return out, False


class Leds:
    def __init__(self, c, pin, regeln):
        """regeln: der LED-Teil aus logic.json (wird live geaendert)."""
        self.regeln = regeln
        self.blink_s = c["options"].get("blink_s", 0.5)
        self.einfach = []
        self.fehler = []
        for l in c["leds"]:
            try:
                p = digitalio.DigitalInOut(pin(l["pin"]))
                p.direction = digitalio.Direction.OUTPUT
                p.value = False
                self.einfach.append(p)
            except Exception as e:
                self.fehler.append("LED %s: %s" % (l.get("pin"), e))
                self.einfach.append(None)
        self.px = None
        self.px_n = 0
        pc = c.get("pixels")
        if pc and pc.get("pin"):
            try:
                import neopixel
                self.px_n = int(pc.get("count", 8))
                kw = {"brightness": float(pc.get("brightness", 0.3)),
                      "auto_write": False}
                ordnung = getattr(neopixel, str(pc.get("order", "GRB")), None)
                if ordnung is not None:
                    kw["pixel_order"] = ordnung
                self.px = neopixel.NeoPixel(pin(pc["pin"]), self.px_n, **kw)
                self.px.fill((0, 0, 0))
                self.px.show()
            except Exception as e:
                self.fehler.append("WS2812: %s" % e)
                self.px = None
        self.zustand = [0] * len(self.einfach)
        self._letzt_px = None
        self._px_zeit = 0.0

    def _blink(self, now):
        return int(now / self.blink_s) % 2 == 0

    def update(self, ctx, now, override=None):
        """override: Funktion(i) -> True/False/None fuer einfache LEDs, z.B.
        die Status-LED im Konfigurationsmodus."""
        ausdr = self.regeln.get("leds", [])
        for i, p in enumerate(self.einfach):
            if p is None:
                continue
            r = ausdr[i] if i < len(ausdr) else {}
            v = None if override is None else override(i)
            if v is None:
                if logik.werten(r.get("on", ""), ctx):
                    v = True
                elif logik.werten(r.get("blink", ""), ctx):
                    v = self._blink(now)
                else:
                    v = False
            if p.value != v:
                p.value = v
            self.zustand[i] = 1 if v else 0

        if self.px is None or now - self._px_zeit < 0.02:    # hoechstens 50 Hz
            return
        self._px_zeit = now
        self.px_rechnen(ctx, now)

    def px_rechnen(self, ctx, now):
        pr = self.regeln.get("pixels", {})
        n = self.px_n
        farben = [(0, 0, 0)] * n

        name = str(pr.get("rpm", "")).lower()
        if name and name in ctx.tele:
            try:
                wert = float(ctx.tele[name])
                mx = pr.get("rpm_max", 100)
                if isinstance(mx, str):
                    mx = float(ctx.tele.get(mx.lower(), 0) or 0)
                mx = float(mx)
                if mx > 0:
                    band, blitz = drehzahlband(
                        wert / mx, n, pr.get("start", 60) / 100.0,
                        (pr.get("flash", 97) / 100.0) if pr.get("flash") else None,
                        [farbe(f) for f in pr.get("colors",
                                                   ["#00ff00", "#ffff00", "#ff0000"])])
                    if blitz:
                        f = farbe(pr.get("flash_color", "#0000ff"))
                        farben = [f if self._blink(now * 4) else (0, 0, 0)] * n
                    else:
                        farben = band
            except (TypeError, ValueError):
                pass

        for r in pr.get("rules", []):
            if not r.get("expr"):
                continue
            if logik.werten(r["expr"], ctx):
                if r.get("blink") and not self._blink(now):
                    continue
                f = farbe(r.get("color", "#ffffff"))
                for i in bereich(r.get("leds", ""), n):
                    farben[i] = f

        if farben != self._letzt_px:
            for i in range(n):
                self.px[i] = farben[i]
            self.px.show()
            self._letzt_px = farben

    def aus(self):
        for p in self.einfach:
            if p is not None:
                p.value = False
        if self.px is not None:
            self.px.fill((0, 0, 0))
            self.px.show()
            self._letzt_px = None
