# SPDX-License-Identifier: GPL-3.0-or-later
# boot.py - UniversalGC, universelle Gamecontroller-Firmware
#
# Liest device.json und meldet das Geraet passend dazu am USB an: Name, PID,
# und einen HID-Descriptor mit genau den Buttons und Achsen, die konfiguriert
# sind. Deshalb braucht jede Aenderung an der Belegung einen Neustart - der
# PC fragt den Aufbau des Geraets nur beim Einstecken ab.
#
# Jeder Schritt ist einzeln abgesichert. Faellt einer aus, laufen die anderen
# trotzdem - und der Grund steht hinterher in boot_out.txt auf CIRCUITPY.
# (Gelernt an der Buttonbox v2.0: dort riss ein einziger Fehler alles mit.)
#
# NOTAUSGANG: Konfigurationstaster beim Einstecken gedrueckt halten, dann
# bleibt CIRCUITPY als Laufwerk sichtbar. Das Geraet kann dann nicht selbst
# speichern, aber man kommt an alle Dateien heran. Ohne Taster: in der
# Weboberflaeche "Neustart mit Laufwerk" oder in der Konsole
#     import merker; merker.wartung()
#
# RUECKFALL: Speichert die Weboberflaeche eine neue Belegung, bleibt die alte
# als device.bak.json liegen und /cfg_pending wird angelegt. Laeuft code.py
# danach 15 Sekunden sauber, loescht es die Markierung. Scheitert der Start
# zweimal hintereinander, meldet boot.py das Geraet mit der alten Belegung an,
# und code.py kopiert sie zurueck.
#
# WICHTIG: boot.py schreibt NICHTS auf das Dateisystem. Waehrend es laeuft,
# hat CircuitPython boot_out.txt offen. Mit storage.remount() und Schreiben
# hier endete boot.py am echten Pico 2 W in "OSError: [Errno 5]" (vermutlich
# genau deshalb). Was boot.py sich merken muss, steht im NVM (merker.py).

import board
import digitalio
import storage
import usb_hid
import os

try:
    import cfg
    import merker
    import pins
except ImportError as e:
    # Noch nicht alles kopiert. boot.py endet hier, das Laufwerk bleibt an.
    print("boot.py: Installation unvollstaendig -", e)
    raise

meldungen = []
FEHLSTARTS_BIS_RUECKFALL = 2

# Ohne diese Dateien laeuft code.py nicht. Fehlt eine, bleibt das Laufwerk
# sichtbar - so ist egal, in welcher Reihenfolge die Dateien kopiert werden.
# (.mpy zaehlt genauso wie .py.)
PFLICHT = ("code", "cfg", "merker", "pins", "eingaben", "achsen", "kalib",
           "logik", "tele", "rumble", "leds", "ble_hid", "web")


def existiert(pfad):
    try:
        os.stat(pfad)
        return True
    except OSError:
        return False


fehlend = [m for m in PFLICHT
           if not (existiert("/%s.py" % m) or existiert("/%s.mpy" % m))]
if not existiert("/index.html"):
    fehlend.append("index.html")


# --- Konfiguration, ggf. Rueckfall auf die alte ------------------------------

rueckfall = merker.lesen(merker.RUECKFALL) == merker.R_MAGIC
if existiert(cfg.PENDING_FILE) and not rueckfall:
    if not merker.verfuegbar():
        meldungen.append("kein NVM - Rueckfall auf alte Belegung nicht moeglich")
    else:
        n = merker.lesen(merker.FEHLSTARTS)
        if n >= FEHLSTARTS_BIS_RUECKFALL and existiert(cfg.BACKUP_FILE):
            rueckfall = True
            merker.setzen(merker.RUECKFALL, merker.R_MAGIC)
            merker.setzen(merker.FEHLSTARTS, 0)
            meldungen.append("neue Belegung startete %dx nicht - alte wird "
                             "zurueckgeholt" % n)
        else:
            merker.setzen(merker.FEHLSTARTS, n + 1)

c, quelle = cfg.load(rueckfall, leise=True)
if quelle == "default":
    meldungen.append("keine lesbare device.json")
elif quelle == "backup":
    meldungen.append("device.json kaputt - Sicherung benutzt")

# --- Wartungsmodus? ----------------------------------------------------------

# Ohne lesbaren Konfigurationstaster gaebe es keinen Weg zurueck an das
# Laufwerk - dann bleibt es sichtbar. Das ist vor allem der Fall bei einem
# frisch bespielten Board ohne device.json: Dort wuerde sonst schon das
# Kopieren der Dateien abbrechen, sobald boot.py einmal gelaufen ist.
wartungsmodus = False
einrichtung = False
pin = c.get("config_pin")
if fehlend:
    einrichtung = True
    meldungen.append("es fehlt: " + ", ".join(fehlend))
elif quelle == "default" or not pin:
    einrichtung = True
else:
    try:
        taster = digitalio.DigitalInOut(pins.board_pin(board, pin))
        taster.direction = digitalio.Direction.INPUT
        taster.pull = digitalio.Pull.UP
        wartungsmodus = not taster.value    # gegen GND: gedrueckt = False
        taster.deinit()                     # Pin freigeben, code.py braucht ihn
    except Exception as e:
        meldungen.append("Taster %s nicht lesbar: %s" % (pin, e))
        einrichtung = True

# Wartungsmodus ohne Taster, angefordert ueber Weboberflaeche oder Konsole.
# Gilt nur fuer diesen einen Start.
if merker.lesen(merker.WARTUNG) == merker.W_MAGIC:
    wartungsmodus = True
    merker.setzen(merker.WARTUNG, 0)

if einrichtung:
    meldungen.append("Einrichtung: Laufwerk bleibt sichtbar")
elif wartungsmodus:
    meldungen.append("Wartungsmodus: CIRCUITPY sichtbar, Speichern aus")
else:
    # Laufwerk aus - aber erst ganz am Ende, nach den Ausgaben (siehe unten).
    meldungen.append("Laufwerk wird abgeschaltet")

# --- USB-Name ----------------------------------------------------------------
#
# Eigene PID je Geraet: Windows legt die Joystick-Konfiguration nach VID/PID
# ab. Zwei CircuitPython-Geraete mit der Werks-PID kaemen sich in die Quere.
# Buttonbox 0x4711, Pedale 0x4712, Lenkrad 0x4713.

u = c["usb"]
try:
    import supervisor
    pid = int(u.get("pid", -1))
    hersteller = str(u.get("manufacturer", "UniversalGC"))[:30]
    produkt = str(u.get("product") or c.get("name") or "UniversalGC")[:30]
    if pid >= 0:
        supervisor.set_usb_identification(manufacturer=hersteller,
                                          product=produkt, pid=pid)
        meldungen.append("USB: %s, PID 0x%04X" % (produkt, pid))
    else:
        supervisor.set_usb_identification(manufacturer=hersteller,
                                          product=produkt)
except Exception as e:
    meldungen.append("USB-Name nicht gesetzt: %s" % e)

# --- HID ---------------------------------------------------------------------

try:
    desc = cfg.descriptor(c)
    laenge = cfg.report_laenge(c)
    geraet = usb_hid.Device(
        report_descriptor=desc,
        usage_page=0x01,                     # Generic Desktop
        usage=cfg.device_usage(c),           # muss zu code.py passen
        report_ids=(cfg.REPORT_ID,),
        in_report_lengths=(laenge,),
        out_report_lengths=(0,),
    )
    usb_hid.enable((geraet,))
    meldungen.append("HID: %d Buttons, %d Achsen, %d Byte" %
                     (cfg.buttons_im_report(c), len(c["axes"]), laenge))
except Exception as e:
    meldungen.append("HID-Geraet nicht angelegt: %s" % e)

# --- Serieller Datenkanal fuer SimHub ----------------------------------------
#
# Zuletzt, weil er der einzige Schritt ist, auf den man zur Not verzichten
# kann. Am Pico meldet sich das Geraet danach mit ZWEI COM-Ports: Konsole und
# Daten.
#
# Der ESP32-S3 hat dafuer nicht genug USB-Endpunkte: nur 4 IN-Endpunkte
# gleichzeitig, jede serielle Schnittstelle braucht 2, Joystick und Laufwerk
# je 1 (Adafruit, "Customizing USB Devices in CircuitPython"). Konsole +
# Datenkanal + Joystick sind schon 5 - CircuitPython geht dann in den
# abgesicherten Modus. Dort laeuft die Telemetrie deshalb ueber die Konsole
# (code.py liest sie von dort, siehe tele.py), und MIDI bleibt aus.

try:
    import usb_midi
    usb_midi.disable()          # braucht niemand, kostet einen Endpunkt
except Exception:
    pass

if c["telemetry"].get("enabled", True):
    if pins.chip() == "esp32s3":
        meldungen.append("Telemetrie ueber die Konsole (ESP32-S3)")
    else:
        try:
            import usb_cdc
            usb_cdc.enable(console=True, data=True)
        except Exception as e:
            meldungen.append("Datenkanal nicht moeglich: %s" % e)

try:
    print("boot.py:", c.get("name"), "(" + quelle + ")")
    for m in meldungen:
        print("  -", m)
except OSError:
    pass            # boot_out.txt nicht schreibbar - das Geraet laeuft trotzdem

# --- Laufwerk abschalten - als allerletzter Schritt -------------------------
#
# Damit wird CIRCUITPY fuer das Geraet selbst beschreibbar. Es steht bewusst
# hinter allen Ausgaben: am Pico 2 W mit CircuitPython 10.3.1 endete boot.py
# mit "OSError: [Errno 5]", und die Meldungen fehlten in boot_out.txt, sobald
# das Laufwerk vorher abgeschaltet wurde. Im Einrichtungsmodus (Laufwerk an)
# lief derselbe Code sauber durch.
if not (einrichtung or wartungsmodus):
    try:
        storage.disable_usb_drive()
    except Exception:
        pass
