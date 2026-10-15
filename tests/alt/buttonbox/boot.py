# boot.py - Pico W Buttonbox v2.1
#
# Jeder Schritt ist einzeln abgesichert. Faellt einer aus, laufen die anderen
# trotzdem - und der Grund steht hinterher in boot_out.txt auf CIRCUITPY.
# In v2.0 riss ein einziger Fehler alles mit: kein Gamepad, kein Webserver,
# und man sah nur "CircuitPython HID" im Geraetemanager.
#
# NOTAUSGANG: WLAN-Taster (GP15) beim Einstecken gedrueckt halten, dann bleibt
# CIRCUITPY als Laufwerk sichtbar. Der Pico kann dann nicht selbst speichern.

TASTER_PIN       = "GP15"   # muss zu WLAN_BTN_PIN in settings.py passen
TELEMETRIE_KANAL = True     # zweiter serieller Kanal fuer SimHub

# Eigene USB-Produkt-ID. -1 laesst die von CircuitPython stehen.
#
# Wozu: Windows merkt sich zu jeder VID/PID, wie das Geraet aufgebaut ist.
# Aendert sich die Zusammensetzung - etwa weil ein zweiter serieller Kanal
# dazukommt - benutzt Windows unter Umstaenden weiter die alte gemerkte
# Konfiguration und zeigt einen Gamecontroller ganz ohne Achsen und Buttons.
# Eine neue PID zwingt Windows, das Geraet von vorn einzulesen.
#
# ACHTUNG: Mit einer neuen PID ist es fuer Windows ein anderes Geraet. Alle
# Tastenbelegungen im Spiel muessen dann neu gesetzt werden. Also erst die
# sanfteren Wege probieren (Geraet im Geraete-Manager entfernen und neu
# einstecken), und das hier nur, wenn das nicht hilft.
USB_PID = 0x4711               # z.B. 0x4711

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
                                          product="Buttonbox", pid=USB_PID)
        meldungen.append("eigene USB-PID: 0x%04X" % USB_PID)
    else:
        supervisor.set_usb_identification(manufacturer="SimRacing",
                                          product="Buttonbox")
except Exception as e:
    meldungen.append("USB-Name nicht gesetzt: %s" % e)

# --- HID-Gamepad -------------------------------------------------------------
#
# Buttonbelegung (Bitpositionen wie in v1, damit Zuordnungen im Spiel bleiben):
#    1-11  Bit  0-10   physische Inputs
#   12-22  Bit 11-21   frei (war die Shift-Ebene)
#   23-38  Bit 22-37   Logik-Buttons
#   39-40  Bit 38-39   Reserve
GAMEPAD_REPORT_DESCRIPTOR = bytes([
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x05,        # Usage (Gamepad)
    0xA1, 0x01,        # Collection (Application)

    0x05, 0x09,        #   Usage Page (Button)
    0x19, 0x01,        #   Usage Minimum (Button 1)
    0x29, 0x28,        #   Usage Maximum (Button 40)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x28,        #   Report Count (40)
    0x81, 0x02,        #   Input (Data, Variable, Absolute)

    0x05, 0x01,                    #   Usage Page (Generic Desktop)
    0x09, 0x33,                    #   Usage (Rx)
    0x09, 0x34,                    #   Usage (Ry)
    0x09, 0x35,                    #   Usage (Rz)
    0x15, 0x00,                    #   Logical Minimum (0)
    0x27, 0xFF, 0xFF, 0x00, 0x00,  #   Logical Maximum (65535)
    0x75, 0x10,                    #   Report Size (16)
    0x95, 0x03,                    #   Report Count (3)
    0x81, 0x02,                    #   Input (Data, Variable, Absolute)

    0xC0               # End Collection
])

# Das ist der wichtigste Schritt - er kommt zuerst und ohne Umschweife.
gamepad = usb_hid.Device(
    report_descriptor=GAMEPAD_REPORT_DESCRIPTOR,
    usage_page=0x01,
    usage=0x05,
    report_ids=(0,),
    in_report_lengths=(11,),   # 5 Byte Buttons + 6 Byte Achsen
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
    meldungen.append("Wartungsmodus: CIRCUITPY sichtbar, Speichern aus")
else:
    try:
        storage.disable_usb_drive()
    except Exception as e:
        meldungen.append("Laufwerk nicht abschaltbar: %s" % e)

# --- Serieller Datenkanal fuer SimHub ----------------------------------------
#
# Zuletzt, weil er der einzige Schritt ist, auf den man zur Not verzichten kann.
# Danach meldet sich der Pico mit ZWEI COM-Ports: REPL-Konsole und Datenkanal.
# Bei Problemen hier oben TELEMETRIE_KANAL = False setzen - dann laeuft alles
# ausser der Telemetrie weiter.
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
    print("boot.py ok - Gamepad aktiv, Laufwerk aus, Datenkanal an")
