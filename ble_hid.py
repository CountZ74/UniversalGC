# SPDX-License-Identifier: GPL-3.0-or-later
# ble_hid.py - derselbe HID-Report zusaetzlich ueber Bluetooth LE
#
# Geht nur auf Chips mit BLE in CircuitPython: ESP32-S3, nRF52840. Der Pico W
# kann es nicht (der Funkchip stellt unter CircuitPython kein BLE bereit) -
# dort meldet start() den Grund, und das Geraet laeuft normal ueber USB.
#
# Am Kabel und per Funk gleichzeitig: jeder Report geht an beide Wege. Windows
# sieht zwei Controller mit gleichem Namen; im Spiel nur einen davon belegen.
#
# WLAN und Bluetooth teilen sich beim ESP32-S3 die Antenne. Solange die
# Weboberflaeche laeuft, wird Bluetooth deshalb pausiert.
#
# Braucht lib/adafruit_ble.
#
# Tempo: Per Funk geht ein Report nur einmal je Verbindungsintervall raus
# (Linux/Windows waehlen gern 30-50 ms). Wer schneller sendet, fuellt nur die
# Warteschlange des Funkstacks - jeder Tastendruck steht dann hinter alten
# Achsenwerten an und kommt spuerbar spaet. Deshalb:
#   - nach dem Verbinden 7,5 ms Intervall erbitten (das kleinste erlaubte),
#   - hoechstens einen Report je Intervall senden, immer nur den neuesten,
#   - den Verbindungsstatus nicht in jeder Runde abfragen.

import time

APPEARANCE = {0x04: 0x03C3, 0x05: 0x03C4}    # Joystick, Gamepad


class BleHid:
    def __init__(self, c, descriptor, usage):
        self.c = c
        self.desc = descriptor
        self.usage = usage
        self.radio = None
        self.adv = None
        self.geraet = None
        self.grund = ""
        self.pausiert = False
        self.verb = False          # zuletzt geprueft: verbunden?
        self.pruefen_ab = 0.0
        self.abstand = 0.0075      # s zwischen zwei Reports (Verbindungsintervall)
        self.gesendet = 0.0
        self.offen = None          # neuester, noch nicht gesendeter Report
        self.letzter = None

    def start(self):
        b = self.c.get("ble") or {}
        if not b.get("enabled"):
            self.grund = "aus (device.json)"
            return False
        try:
            import adafruit_ble
            from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
            from adafruit_ble.services.standard.hid import HIDService
            from adafruit_ble.services.standard.device_info import DeviceInfoService
        except ImportError as e:
            self.grund = "nicht verfuegbar: %s" % e
            return False
        try:
            hid = HIDService(hid_descriptor=self.desc)
            DeviceInfoService(manufacturer=self.c["usb"].get("manufacturer", "UniversalGC"),
                              model_number=self.c.get("name", "UniversalGC"))
            self.adv = ProvideServicesAdvertisement(hid)
            self.adv.appearance = APPEARANCE.get(self.usage, 0x03C3)
            self.radio = adafruit_ble.BLERadio()
            name = b.get("name") or self.c.get("name") or "UniversalGC"
            self.radio.name = name[:20]
            for d in hid.devices:
                if getattr(d, "usage", None) == self.usage:
                    self.geraet = d
                    break
            if self.geraet is None and hid.devices:
                self.geraet = hid.devices[0]
            self.radio.start_advertising(self.adv)
            self.grund = "bereit"
            return True
        except Exception as e:
            # Pico W: _bleio meldet hier, dass es keinen BLE-Adapter gibt
            self.grund = "nicht moeglich: %s" % e
            self.radio = None
            return False

    @property
    def verbunden(self):
        return self.radio is not None and self.verb

    def _intervall(self, erbitten):
        """Kurzes Verbindungsintervall erbitten und das tatsaechliche merken
        (die Aushandlung dauert, deshalb wird es spaeter erneut gelesen)."""
        try:
            for v in self.radio.connections:
                if erbitten:
                    try:
                        v.connection_interval = 7.5
                    except Exception:
                        pass
                ms = v.connection_interval
                if ms:
                    self.abstand = max(0.0075, ms / 1000.0)
        except Exception:
            pass

    def schritt(self, now=None):
        """Verbindung pruefen (alle 0,25 s), nach Abbruch wieder werben,
        zurueckgehaltenen Report senden."""
        if self.radio is None or self.pausiert:
            return
        if now is None:
            now = time.monotonic()
        if now >= self.pruefen_ab:
            self.pruefen_ab = now + 0.25
            try:
                war = self.verb
                self.verb = self.radio.connected
                if self.verb:
                    self._intervall(not war)
                    if not war:
                        self.offen = self.letzter    # Stand nach dem Verbinden
                if not self.verb and not self.radio.advertising:
                    self.radio.start_advertising(self.adv)
            except Exception:
                pass
        if self.offen is not None and now - self.gesendet >= self.abstand:
            self._raus(now)

    def _raus(self, now):
        r, self.offen = self.offen, None
        self.gesendet = now
        try:
            self.geraet.send_report(r)
        except Exception:
            pass

    def senden(self, report):
        if self.geraet is None or self.pausiert:
            return
        self.letzter = bytes(report)
        if not self.verb:
            return
        self.offen = self.letzter
        now = time.monotonic()
        if now - self.gesendet >= self.abstand:
            self._raus(now)

    def pause(self):
        if self.radio is None:
            return
        self.pausiert = True
        try:
            self.radio.stop_advertising()
        except Exception:
            pass
        try:
            for v in self.radio.connections:
                v.disconnect()
        except Exception:
            pass

    def weiter(self):
        if self.radio is None:
            return
        self.pausiert = False
        self.verb = False
        self.pruefen_ab = 0.0
        self.schritt()

    def status(self):
        if self.radio is None:
            return self.grund
        if self.pausiert:
            return "pausiert (WLAN aktiv)"
        return "verbunden" if self.verbunden else "wartet auf Kopplung"
