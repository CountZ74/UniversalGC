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
# speichern, aber man kommt an alle Dateien heran.
#
# RUECKFALL: Speichert die Weboberflaeche eine neue Belegung, bleibt die alte
# als device.bak.json liegen und /cfg_pending wird angelegt. Laeuft code.py
# danach 15 Sekunden sauber, loescht es die Markierung. Scheitert der Start
# zweimal hintereinander, holt boot.py die alte Belegung zurueck.

import board
import digitalio
import storage
import usb_hid
import os

import cfg

meldungen = []
FEHLSTARTS_BIS_RUECKFALL = 2


def existiert(pfad):
    try:
        os.stat(pfad)
        return True
    except OSError:
        return False


# --- Konfiguration -----------------------------------------------------------

c, quelle = cfg.load()
if quelle != "device":
    meldungen.append("device.json fehlt oder ist kaputt - benutze %s" % quelle)

# --- Wartungsmodus? ----------------------------------------------------------

# Ohne lesbaren Konfigurationstaster gaebe es keinen Weg zurueck an das
# Laufwerk - dann bleibt es sichtbar. Das ist vor allem der Fall bei einem
# frisch bespielten Board ohne device.json: Dort wuerde sonst schon das
# Kopieren der Dateien abbrechen, sobald boot.py einmal gelaufen ist.
wartungsmodus = False
einrichtung = False
pin = c.get("config_pin")
if quelle == "default" or not pin:
    einrichtung = True
else:
    try:
        taster = digitalio.DigitalInOut(getattr(board, pin))
        taster.direction = digitalio.Direction.INPUT
        taster.pull = digitalio.Pull.UP
        wartungsmodus = not taster.value    # gegen GND: gedrueckt = False
        taster.deinit()                     # Pin freigeben, code.py braucht ihn
    except Exception as e:
        meldungen.append("Taster %s nicht lesbar: %s" % (pin, e))
        einrichtung = True

# Wartungsmodus ohne Taster: die Weboberflaeche oder die Konsole legt /wartung
# an und startet neu (siehe README). Die Markierung gilt nur fuer diesen einen
# Start und wird gleich wieder geloescht.
try:
    os.stat(cfg.WARTUNG_FILE)
    wartungsmodus = True
    try:
        storage.remount("/", readonly=False)
        os.remove(cfg.WARTUNG_FILE)
        storage.remount("/", readonly=True)     # Laufwerk wieder fuer den PC
    except Exception as e:
        meldungen.append("Wartungs-Markierung nicht loeschbar: %s" % e)
except OSError:
    pass

if einrichtung:
    meldungen.append("Einrichtung: kein Konfigurationstaster - CIRCUITPY "
                     "bleibt sichtbar, das Geraet speichert nichts")
elif wartungsmodus:
    meldungen.append("Wartungsmodus: CIRCUITPY sichtbar, Speichern aus")
else:
    # Laufwerk aus. Damit wird CIRCUITPY fuer das Geraet selbst beschreibbar.
    try:
        storage.disable_usb_drive()
    except Exception as e:
        meldungen.append("Laufwerk nicht abschaltbar: %s" % e)

    # --- Rueckfall auf die letzte funktionierende Belegung -------------------
    if existiert(cfg.PENDING_FILE):
        try:
            storage.remount("/", readonly=False)
            try:
                with open(cfg.PENDING_FILE) as f:
                    versuche = int(f.read().strip() or "0")
            except ValueError:
                versuche = 0
            if versuche >= FEHLSTARTS_BIS_RUECKFALL and existiert(cfg.BACKUP_FILE):
                with open(cfg.BACKUP_FILE) as f:
                    alt = f.read()
                with open(cfg.CONFIG_FILE, "w") as f:
                    f.write(alt)
                os.remove(cfg.PENDING_FILE)
                meldungen.append("neue Belegung startete %dx nicht - alte "
                                 "zurueckgeholt" % versuche)
                c, quelle = cfg.load()
            else:
                with open(cfg.PENDING_FILE, "w") as f:
                    f.write(str(versuche + 1))
            # Bewusst nicht wieder schreibgeschuetzt: code.py muss speichern.
        except Exception as e:
            meldungen.append("Rueckfall-Pruefung nicht moeglich: %s" % e)

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
# kann. Danach meldet sich das Geraet mit ZWEI COM-Ports: Konsole und Daten.

if c["telemetry"].get("enabled", True):
    try:
        import usb_cdc
        usb_cdc.enable(console=True, data=True)
    except Exception as e:
        meldungen.append("Datenkanal nicht moeglich: %s" % e)

print("boot.py:", c.get("name"), "(" + quelle + ")")
for m in meldungen:
    print("  -", m)
