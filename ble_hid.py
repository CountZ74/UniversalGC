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
        try:
            return self.radio is not None and self.radio.connected
        except Exception:
            return False

    def schritt(self):
        """Nach einem Verbindungsabbruch wieder werben."""
        if self.radio is None or self.pausiert:
            return
        try:
            if not self.radio.connected and not self.radio.advertising:
                self.radio.start_advertising(self.adv)
        except Exception:
            pass

    def senden(self, report):
        if self.geraet is None or self.pausiert or not self.verbunden:
            return
        try:
            self.geraet.send_report(report)
        except Exception:
            pass

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
        self.schritt()

    def status(self):
        if self.radio is None:
            return self.grund
        if self.pausiert:
            return "pausiert (WLAN aktiv)"
        return "verbunden" if self.verbunden else "wartet auf Kopplung"
