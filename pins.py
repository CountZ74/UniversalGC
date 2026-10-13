# SPDX-License-Identifier: GPL-3.0-or-later
# pins.py - welche Pins hat dieses Board, und was koennen sie?
#
# Die Pinnamen in device.json sind die Namen aus dem board-Modul (GP2 beim
# Pico, IO4 oder D5 bei ESP32-S3-Boards). Mehrere Namen koennen denselben
# Anschluss meinen (GP26 und A0) - verglichen wird deshalb ueber den Namen
# des Chip-Pins aus microcontroller.pin (GPIO26).
#
# Was analog geht oder reserviert ist, haengt am Chip, nicht am Board:
#   RP2040 / RP2350   Analog: GPIO26-29
#   ESP32-S3          Analog: GPIO1-20, aber GPIO11-20 (ADC2) NICHT bei
#                     aktivem WLAN. GPIO19/20 sind USB, GPIO26-37 haengen bei
#                     den meisten Modulen am Flash/PSRAM.

import sys

# Board-Namen, die keine freien Anschluesse sind. SDA, TX usw. bleiben drin:
# bei kleinen Boards (QT Py) sind das die einzigen Namen mancher Pins.
NICHT_ANBIETEN = ("VBUS_SENSE", "VOLTAGE_MONITOR", "SMPS_MODE",
                  "NEOPIXEL_POWER", "BOOT")


def chip():
    p = sys.platform.lower()
    if "rp2350" in p:
        return "rp2350"
    if "rp2040" in p:
        return "rp2040"
    if "esp" in p:
        return "esp32s3"     # andere ESP32 koennen kein USB-HID
    return p


def _gpio_nummer(mcname):
    if mcname and mcname.startswith("GPIO"):
        try:
            return int(mcname[4:])
        except ValueError:
            return None
    return None


def analog_moeglich(chipname, nummer):
    if nummer is None:
        return False
    if chipname in ("rp2040", "rp2350"):
        return 26 <= nummer <= 29
    if chipname == "esp32s3":
        return 1 <= nummer <= 20
    return True      # unbekannter Chip: nicht pauschal ablehnen


def reserviert(chipname, nummer):
    """Grund als Text oder None."""
    if nummer is None:
        return None
    if chipname == "esp32s3":
        if nummer in (19, 20):
            return "USB"
        if 26 <= nummer <= 37:
            return "Flash/PSRAM"
    if chipname in ("rp2040", "rp2350") and nummer in (23, 24, 25, 29):
        return "Funkchip (Pico W)"
    return None


# Je nach Board heisst derselbe Chip-Pin IO21 (Espressif DevKitC), GPIO21
# (YD-ESP32-S3 und andere) oder GP21 (Pico). Kennt das Board einen Namen
# nicht, werden die anderen Schreibweisen mit derselben Nummer probiert -
# so passen die Vorlagen auf jedes Board. "D21" bleibt bewusst aussen vor:
# bei Adafruit-Boards ist D5 eine Beschriftung, nicht GPIO5.
PRAEFIXE = ("GPIO", "IO", "GP")


def schreibweisen(name):
    """'IO21' -> ['IO21', 'GPIO21', 'GP21'] (der Originalname zuerst)."""
    name = str(name)
    out = [name]
    for p in PRAEFIXE:
        if name.startswith(p) and name[len(p):].isdigit():
            nr = name[len(p):]
            for q in PRAEFIXE:
                if q + nr not in out:
                    out.append(q + nr)
            break
    return out


def board_pin(board_modul, name):
    """Pin-Objekt zu einem Namen, mit Ausweichen auf andere Schreibweisen."""
    for n in schreibweisen(name):
        if hasattr(board_modul, n):
            return getattr(board_modul, n)
    raise AttributeError("Pin %s gibt es auf diesem Board nicht" % name)


class Pins:
    def __init__(self, board_modul=None, mc_pin_modul=None, chipname=None):
        if board_modul is None:
            import board as board_modul
        if mc_pin_modul is None:
            import microcontroller
            mc_pin_modul = microcontroller.pin
        self.board = board_modul
        self.chip = chipname or chip()
        mc = {}
        for n in dir(mc_pin_modul):
            if n.startswith("_"):
                continue
            mc[id(getattr(mc_pin_modul, n))] = n
        self.liste = {}      # board-Name -> Info
        gruppen = {}
        for n in dir(board_modul):
            if n.startswith("_") or n in NICHT_ANBIETEN:
                continue
            obj = getattr(board_modul, n)
            if type(obj).__name__ != "Pin":
                continue
            mcname = mc.get(id(obj))
            schluessel = mcname or ("board." + n)
            nr = _gpio_nummer(mcname)
            self.liste[n] = {
                "id": schluessel,
                "nr": nr,
                "analog": analog_moeglich(self.chip, nr),
                "res": reserviert(self.chip, nr),
            }
            gruppen.setdefault(schluessel, []).append(n)
        self.gruppen = gruppen

    def _info(self, name):
        for n in schreibweisen(name):
            i = self.liste.get(n)
            if i is not None:
                return i
        return None

    def objekt(self, name):
        return board_pin(self.board, name)

    def pin_id(self, name):
        i = self._info(name)
        if i is None:
            return None
        if i["res"]:
            return None
        return i["id"]

    def analog_ok(self, name):
        i = self._info(name)
        return bool(i and i["analog"])

    def adc2(self, name):
        """ESP32-S3: Analogpin, der bei aktivem WLAN nicht misst."""
        i = self._info(name)
        return bool(self.chip == "esp32s3" and i and i["nr"] and 11 <= i["nr"] <= 20)

    def json(self):
        """Fuer die Weboberflaeche: ein Eintrag je Anschluss, mit allen Namen.

        Bevorzugt wird der Name, der wie der Chip-Pin aussieht (GP2, IO4),
        damit die Liste dem Aufdruck auf der Platine folgt.
        """
        out = []
        for schluessel, namen in self.gruppen.items():
            namen = sorted(namen, key=lambda n: (not (n.startswith("GP") or n.startswith("IO")), n))
            info = self.liste[namen[0]]
            out.append({"n": namen[0], "alias": namen[1:], "a": info["analog"],
                        "nr": info["nr"], "r": info["res"]})
        out.sort(key=lambda e: (e["nr"] is None, e["nr"] or 0, e["n"]))
        return out
