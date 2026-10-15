# boot.py - Pico W Pedale v9.9
#
# Jeder Schritt ist einzeln abgesichert. Faellt einer aus, laufen die anderen
# trotzdem - und der Grund steht hinterher in boot_out.txt auf CIRCUITPY.
# (Dieselbe Absicherung wie in der Buttonbox: dort hatte ein einziger Fehler
# frueher alles mitgerissen, und man sah nur "CircuitPython HID".)
#
# NOTAUSGANG: WLAN-Taster (GP3) beim Einstecken gedrueckt halten, dann bleibt
# CIRCUITPY als Laufwerk sichtbar. Der Pico kann dann nicht selbst speichern.

TASTER_PIN       = "GP3"    # muss zu WIFI_BTN_PIN in settings.py passen
TELEMETRIE_KANAL = True     # zweiter serieller Kanal fuer SimHub (Rumble)

# Eigene USB-Produkt-ID. -1 laesst die von CircuitPython stehen.
#
# Alle CircuitPython-Geraete melden sich ab Werk mit derselben VID/PID. Windows
# legt seine Joystick-Konfiguration aber nur nach VID/PID ab, nicht nach
# Seriennummer - zwei CircuitPython-Geraete am selben Rechner teilen sich also
# einen Eintrag und kommen sich in die Quere. Die Buttonbox hat 0x4711.
#
# ACHTUNG: Eine geaenderte PID ist fuer Windows ein neues Geraet. Alle
# Achs- und Tastenbelegungen im Spiel muessen danach neu gesetzt werden.
# Das ist bei diesem Update ohnehin faellig, weil sich der Descriptor aendert.
USB_PID = 0x4712

import board
import digitalio
import storage
import usb_hid

meldungen = []

# --- USB-Name ----------------------------------------------------------------

try:
    import supervisor
    if USB_PID >= 0:
        supervisor.set_usb_identification(manufacturer="SimRacing",
                                          product="Pedale", pid=USB_PID)
        meldungen.append("eigene USB-PID: 0x%04X" % USB_PID)
    else:
        supervisor.set_usb_identification(manufacturer="SimRacing",
                                          product="Pedale")
except Exception as e:
    meldungen.append("USB-Name nicht gesetzt: %s" % e)

# --- HID-Joystick ------------------------------------------------------------
#
# 3 Achsen Rx, Ry, Rz mit je 16 bit, unsigned 0..65535. Keine Buttons - Pedale
# haben keine, und ein Geraet ohne Buttons wird von Spielen seltener als
# Menue-Controller behandelt (seit v9.9).
#
# Seit v9.8 als Joystick mit Rx/Ry/Rz statt als Gamepad mit X/Y/Z: Automobilista
# 2 und Project CARS steuern ihr Menue ueber X/Y von Gamepads. Ein losgelassenes
# Pedal steht auf 0, bei einer Achse mit Mitte 32768 ist das voller Anschlag -
# das Menue scrollte dadurch von selbst. code.py sucht das Geraet ueber die
# Usage (0x04) - beide Dateien muessen deshalb zusammen aktualisiert werden.
#
# Bis v9.5 waren die Achsen 8 bit signed (-127..127), also 255 Stufen. Der
# AS5600 haengt am 12-bit-ADC und liefert ueber einen typischen Pedalweg rund
# 1200 bis 2400 unterscheidbare Werte, die Waegezelle noch deutlich mehr -
# davon kam am USB nur ein Bruchteil an. Mit 16 bit ist der Descriptor nicht
# mehr die Engstelle.
#
# Report-Aufbau (6 Byte Nutzdaten, die Report-ID kommt vom Stack davor):
#   Byte 0-1   Rx (Gas),      little endian
#   Byte 2-3   Ry (Bremse)
#   Byte 4-5   Rz (Kupplung)
GAMEPAD_DESCRIPTOR = bytes((
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x04,        # Usage (Joystick)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x04,        #   Report ID (4)

    # Achsen Rx, Ry, Rz (je 16 bit, 0..65535)
    0x05, 0x01,                    #   Usage Page (Generic Desktop)
    0x09, 0x33,                    #   Usage (Rx)  Gas
    0x09, 0x34,                    #   Usage (Ry)  Bremse
    0x09, 0x35,                    #   Usage (Rz)  Kupplung
    0x15, 0x00,                    #   Logical Minimum (0)
    0x27, 0xFF, 0xFF, 0x00, 0x00,  #   Logical Maximum (65535)
    0x75, 0x10,                    #   Report Size (16)
    0x95, 0x03,                    #   Report Count (3)
    0x81, 0x02,                    #   Input (Data, Variable, Absolute)

    0xC0,              # End Collection
))

# Der wichtigste Schritt - er kommt zuerst und ohne Umschweife.
gamepad = usb_hid.Device(
    report_descriptor=GAMEPAD_DESCRIPTOR,
    usage_page=0x01,         # Generic Desktop
    usage=0x04,              # Joystick (muss zu code.py passen)
    report_ids=(4,),
    in_report_lengths=(6,),  # 3 Achsen zu je 2 Byte
    out_report_lengths=(0,),
)

usb_hid.enable((gamepad,))

# --- Laufwerk oder Speichern -------------------------------------------------

wartungsmodus = False
try:
    taster = digitalio.DigitalInOut(getattr(board, TASTER_PIN))
    taster.direction = digitalio.Direction.INPUT
    taster.pull = digitalio.Pull.UP
    wartungsmodus = not taster.value    # gegen GND: gedrueckt = False
    taster.deinit()                     # Pin freigeben, code.py braucht ihn
except Exception as e:
    meldungen.append("Taster %s nicht lesbar: %s" % (TASTER_PIN, e))

if wartungsmodus:
    # Laufwerk bleibt sichtbar. Der Pico kann dann NICHT selbst speichern,
    # code.py meldet das in der Weboberflaeche.
    meldungen.append("Wartungsmodus: CIRCUITPY sichtbar, Speichern aus")
else:
    # Normalbetrieb: Laufwerk aus. Damit wird CIRCUITPY fuer den Pico selbst
    # beschreibbar, calibration.json kann gespeichert werden.
    try:
        storage.disable_usb_drive()
    except Exception as e:
        meldungen.append("Laufwerk nicht abschaltbar: %s" % e)

# --- Serieller Datenkanal fuer SimHub ----------------------------------------
#
# Zuletzt, weil er der einzige Schritt ist, auf den man zur Not verzichten kann.
# Danach meldet sich der Pico mit ZWEI COM-Ports: REPL-Konsole und Datenkanal.
# Ueber den Datenkanal schickt SimHub die Rumble-Staerken.
# Bei Problemen hier oben TELEMETRIE_KANAL = False setzen - dann laeuft alles
# ausser dem Rumble weiter.
if TELEMETRIE_KANAL:
    try:
        import usb_cdc
        usb_cdc.enable(console=True, data=True)
    except Exception as e:
        meldungen.append("Datenkanal nicht moeglich: %s" % e)

# --- Ergebnis ----------------------------------------------------------------

if meldungen:
    print("boot.py Hinweise:")
    for m in meldungen:
        print("  -", m)
else:
    print("boot.py ok - Joystick aktiv (16 bit, ohne Buttons), Laufwerk aus, Datenkanal an")
