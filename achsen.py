# SPDX-License-Identifier: GPL-3.0-or-later
# achsen.py - Achsen lesen: Poti/Hall, AS5600, Waegezelle (HX711), Encoder
#
# Jede Achse liefert einen Rohwert; was daraus wird (Kalibrierung, Totzone,
# Kennlinie), steht in kalib.py. Dort ist auch erklaert, warum der AS5600 als
# Kreisgroesse behandelt wird.

import time
import kalib

try:
    import analogio
    import digitalio
except ImportError:          # auf dem PC
    analogio = digitalio = None


# --- HX711 -------------------------------------------------------------------
#
# Ueber die PIO-Einheit des RP2040/RP2350 (Pedale v9.5): die 25 Taktimpulse
# kommen aus der Hardware, eine Lesung kostet rund 225 us statt 13,8 ms
# Bit-Banging in Python. Der ESP32-S3 hat keine PIO, dort laeuft automatisch
# Bit-Banging ueber adafruit_hx711 - langsamer, aber fuer eine Achse am
# Lenkrad ausreichend.
#
#   wait 0 pin 0   DOUT wird low, sobald eine Wandlung fertig ist
#   24x            SCK high, Bit einlesen, SCK low
#   1x             25. Impuls: Kanal A, Gain 128 fuer die naechste Wandlung
#   push           Wort in die FIFO
#
# SCK ist an jeder Stelle, an der das Programm warten kann, low. Bleibt SCK
# laenger als 60 us high, schaltet sich der HX711 ab.
HX711_PIO_QUELLE = """
.program hx711
.side_set 1
    wait 0 pin 0        side 0
    set  x, 23          side 0
bitloop:
    nop                 side 1 [3]
    in   pins, 1        side 1
    jmp  x-- bitloop    side 0 [3]
    nop                 side 1 [3]
    nop                 side 0 [3]
    push                side 0
"""


class HX711:
    def __init__(self, dt, sck, modus="pio", filter_n=8):
        self.letzter = 0
        self.zaehler = 0         # Wandlungen seit der letzten Ratenmessung
        self.gesamt = 0          # Wandlungen insgesamt, fuer den Filter
        self.rate = 0
        self._rate_t = 0.0
        self.tara = 0
        self.modus = modus
        self.sm = None
        self._buf = None
        self._data = None
        self._kanal = None
        # Gleitender Mittelwert (Pedale v9.7): ein Rumble-Motor am Bremspad
        # faltet sich bei 50 Hz Motor und 80 Hz Abtastung als 30-Hz-Zappeln
        # in den Wert. Gemittelt wird nur ueber echte neue Wandlungen.
        self.filter_n = max(1, int(filter_n))
        self._fbuf = [0] * self.filter_n
        self._fi = 0
        self._fsum = 0
        self._fz = -1
        self._finit = False

        if modus == "pio":
            try:
                import rp2pio
                import adafruit_pioasm
                from array import array
                self.sm = rp2pio.StateMachine(
                    adafruit_pioasm.assemble(HX711_PIO_QUELLE),
                    frequency=1_000_000,
                    first_in_pin=dt, in_pin_count=1,
                    first_sideset_pin=sck, sideset_pin_count=1,
                    initial_sideset_pin_state=0,
                    initial_sideset_pin_direction=1,
                    auto_push=False, in_shift_right=False)
                self._buf = array("I", [0] * 8)
            except Exception as e:
                print("HX711: PIO nicht moeglich, weiter mit Bit-Banging:", e)
                if self.sm is not None:
                    try:
                        self.sm.deinit()
                    except Exception:
                        pass
                    self.sm = None
                self.modus = "bitbang"
        if self.modus != "pio":
            from adafruit_hx711.hx711 import HX711 as _HX
            from adafruit_hx711.analog_in import AnalogIn as _HXIn
            self._data = digitalio.DigitalInOut(dt)
            self._data.direction = digitalio.Direction.INPUT
            clk = digitalio.DigitalInOut(sck)
            clk.direction = digitalio.Direction.OUTPUT
            hx = _HX(self._data, clk)
            self._kanal = _HXIn(hx, _HX.CHAN_A_GAIN_128)

        time.sleep(0.5)
        for _ in range(5):
            self.tara = self.roh_warten()
            time.sleep(0.2)
        self.letzter = self.tara

    def poll(self):
        """Nicht blockierend: neuester Wert oder der letzte bekannte."""
        if self.sm is not None:
            n = self.sm.in_waiting
            if n:
                self.zaehler += n
                self.gesamt += n
                if n > len(self._buf):
                    n = len(self._buf)
                self.sm.readinto(self._buf, end=n)
                v = self._buf[n - 1] & 0xFFFFFF
                if v & 0x800000:                  # 24-Bit Zweierkomplement
                    v -= 0x1000000
                self.letzter = v
        elif not self._data.value:                # DT low = Daten bereit
            try:
                self.letzter = self._bang()
                self.zaehler += 1
                self.gesamt += 1
            except Exception:
                pass
        return self.letzter

    def _bang(self):
        v = self._kanal.value
        if v & 0x80000000:
            v = v - 0x100000000
        return v

    def roh_warten(self):
        """Blockierend: wartet auf einen frischen Wert (nur beim Tarieren)."""
        if self.sm is None:
            return self._bang()
        ende = time.monotonic() + 0.5
        while time.monotonic() < ende:
            if self.sm.in_waiting:
                return self.poll()
        return self.letzter

    def tarieren(self):
        time.sleep(0.2)
        self.tara = self.poll()
        self._finit = False
        return self.tara

    def wert(self):
        """Tariert, gefiltert, nie negativ."""
        v = self.poll() - self.tara
        if self.filter_n > 1:
            if not self._finit:
                self._fbuf = [v] * self.filter_n
                self._fsum = v * self.filter_n
                self._fz = self.gesamt
                self._finit = True
            elif self.gesamt != self._fz:
                self._fz = self.gesamt
                self._fsum += v - self._fbuf[self._fi]
                self._fbuf[self._fi] = v
                self._fi = (self._fi + 1) % self.filter_n
            v = self._fsum // self.filter_n
        return v if v > 0 else 0

    def rate_messen(self, now):
        if now - self._rate_t >= 1.0:
            self.rate = self.zaehler
            self.zaehler = 0
            self._rate_t = now


# --- Achse -------------------------------------------------------------------

class Achse:
    def __init__(self, acfg, pin, cal, mittel=4):
        self.cfg = acfg
        self.typ = acfg.get("type", "pot")
        self.name = acfg.get("name") or acfg.get("usage", "?")
        self.cal = cal
        self.mittel = max(1, int(mittel))
        self.dz, self.mg = kalib.raender(acfg)
        self.adc = None
        self.hx = None
        self.enc = None
        self.enc_pos = 0
        self.fehler = None
        try:
            if self.typ in ("pot", "as5600"):
                self.adc = analogio.AnalogIn(pin(acfg["pin"]))
            elif self.typ == "hx711":
                self.hx = HX711(pin(acfg["dt"]), pin(acfg["sck"]),
                                acfg.get("mode", "pio"), acfg.get("filter", 8))
            elif self.typ == "encoder":
                import rotaryio
                self.enc = rotaryio.IncrementalEncoder(
                    pin(acfg["a"]), pin(acfg["b"]),
                    divisor=int(acfg.get("divisor", 4)))
                self.schritte = max(1, int(acfg.get("steps", 32)))
                # Mittelstellung fuer Encoder, die z.B. eine Bremsbalance
                # einstellen; sonst Start bei 0
                self.enc_pos = self.schritte // 2 if acfg.get("center") else 0
                self._enc_letzte = self.enc.position
        except Exception as e:
            self.fehler = "%s: %s" % (self.name, e)
            print("Achse", self.fehler)

    def roh(self):
        """Ein einzelner Rohwert."""
        if self.adc is not None:
            return self.adc.value
        if self.hx is not None:
            return self.hx.wert()
        if self.enc is not None:
            p = self.enc.position
            d = p - self._enc_letzte
            self._enc_letzte = p
            if self.cfg.get("reverse"):
                d = -d
            self.enc_pos += d
            if self.enc_pos < 0:
                self.enc_pos = 0
            elif self.enc_pos > self.schritte:
                self.enc_pos = self.schritte
            return self.enc_pos
        return 0

    def roh_mittel(self, n=None):
        """Gemittelter Rohwert. Waegezelle und Encoder ohne Mittelung."""
        n = self.mittel if n is None else n
        if self.adc is None or n <= 1:
            return self.roh()
        if self.typ == "as5600":
            return kalib.kreis_mittel([self.adc.value for _ in range(n)])
        s = 0
        for _ in range(n):
            s += self.adc.value
        return s // n

    def norm(self, raw):
        if self.typ == "encoder":
            return raw / self.schritte
        return kalib.norm(raw, self.cal, self.dz, self.mg)

    def hid(self, raw):
        return kalib.ausgabe(self.norm(raw), self.cal)

    def prozent_ein(self, raw):
        return int(self.norm(raw) * 100)

    def prozent_aus(self, raw):
        return int(kalib.kurve(self.norm(raw) * 100,
                               self.cal.get("curve", kalib.DEFAULT_CURVE)))
