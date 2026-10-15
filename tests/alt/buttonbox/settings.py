# settings.py - Konfiguration Pico W Buttonbox v2

# --- WLAN Access Point -------------------------------------------------------

SSID       = "Pico-Buttonbox"
PASSWORD   = "buttonbox123"   # min. 8 Zeichen, leer = offenes Netz
AP_CHANNEL = 6
WEB_PORT   = 80

# --- Pins --------------------------------------------------------------------

# Potentiometer / Drehregler
ACHS_PINS  = ["GP26", "GP27", "GP28"]
ACHS_NAMEN = ["Achse 1", "Achse 2", "Achse 3"]

# Physische Inputs in der Reihenfolge b0, b1, b2, ...
# Die Reihenfolge bestimmt die Buttonnummer: b0 = Button 1, b1 = Button 2, ...
INPUT_PINS = [
    "GP2", "GP3", "GP4", "GP5",     # b0-b3   Taster 1-4
    "GP12",                          # b4      Anlasser
    "GP6", "GP7", "GP8", "GP9",     # b5-b8   Schalter 1-4
    "GP10", "GP11",                  # b9-b10  Zuendung 1+2
]
INPUT_NAMEN = [
    "Taster 1", "Taster 2", "Taster 3", "Taster 4",
    "Anlasser",
    "Schalter 1", "Schalter 2", "Schalter 3", "Schalter 4",
    "Zuendung 1", "Zuendung 2",
]

WLAN_BTN_PIN = "GP15"    # muss zu TASTER_PIN in boot.py passen
LED_PIN      = "GP16"    # Anlasser-LED

# --- Verhalten ---------------------------------------------------------------

# Entprellzeit der Taster und Schalter in Sekunden.
DEBOUNCE_S = 0.02

# Blinktakt der LED in Sekunden (halbe Periode).
BLINK_S = 0.5

# Ab welcher Aenderung eines Achswerts ein neuer HID-Report faellig wird.
# 0 = bei jeder Aenderung senden. Hoeher setzen, wenn ein verrauschtes Poti
# dauernd Reports ausloest. 128 von 65535 sind rund 0,2 Prozent.
ACHS_SCHWELLE = 128

# Rand in Prozent, der beim Kalibrieren an beiden Enden abgezogen wird, damit
# die Anschlaege zuverlaessig 0 und 100 Prozent erreichen.
ACHS_RAND_PCT = 1.0

# --- Telemetrie von SimHub ---------------------------------------------------

# Serieller Rueckkanal einschalten. Braucht usb_cdc.enable(data=True) in boot.py.
TELEMETRIE = True

# Nach dieser Zeit ohne neue Zeile gelten alle Telemetriewerte als ungueltig.
# Damit bleibt die LED nicht haengen, wenn SimHub beendet wird.
TELEMETRIE_TIMEOUT_S = 2.0

# Erwartetes Format einer Zeile von SimHub, abgeschlossen mit \n:
#     motor=1;rpm=1450;gang=3
# Die Namen sind frei waehlbar und lassen sich direkt in den Logikausdruecken
# verwenden, genau wie b0 bis b10.
