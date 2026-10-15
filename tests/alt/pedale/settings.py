# settings.py - Konfiguration Pico W Pedale Controller v9

# WLAN Access Point
AP_SSID     = "Pico-Pedale"
AP_PASSWORD = "pedale123"   # min. 8 Zeichen, leer = offenes Netz
AP_CHANNEL  = 6

# Webserver
WEB_PORT    = 80

# LED-Pin
LED_PIN     = "GP16"

# WLAN-Taster Pin (muss zu TASTER_PIN in boot.py passen)
WIFI_BTN_PIN = "GP3"

# ADC Pins: [Gas, Bremse, Kupplung]
ADC_PINS   = ["GP26", "GP27", "GP28"]
ACHS_NAMEN = ["Gas", "Bremse", "Kupplung"]

# Bremsentyp: "adc" = AS5600 analog, "hx711" = Waegezelle
BREMSE_TYP = "hx711"

# HX711 Pins (nur relevant wenn BREMSE_TYP = "hx711")
HX711_DT  = "GP1"   # Daten-Pin
HX711_SCK = "GP0"   # Clock-Pin

# Wie der HX711 ausgelesen wird:
#   "pio"     ueber die PIO-Einheit des RP2040. Eine Lesung kostet rund 225 us
#             statt 13,8 ms, damit kommen alle 80 Wandlungen pro Sekunde an und
#             die Hauptschleife blockiert nicht. Braucht adafruit_pioasm in lib/.
#   "bitbang" die alte Variante ueber adafruit_hx711. Nur als Rueckfallebene.
# Bei "pio" schaltet die Firmware automatisch auf "bitbang" um, wenn die
# PIO-Einheit nicht verfuegbar ist - die Konsole sagt dann, warum.
HX711_MODE = "pio"

# ---------------------------------------------------------------------------
# Neu in v9 - alle optional, die Werte hier sind die Defaults
# ---------------------------------------------------------------------------

# Totzone am Pedalanfang in Prozent. Faengt Sensorrauschen ab, damit das
# losgelassene Pedal sicher bei 0 steht. Hoeher setzen, wenn die Anzeige im
# Ruhezustand zappelt; niedriger, wenn das Pedal zu spaet anspricht.
DEADZONE_PCT = 1.5

# Sicherheitsreserve beim Sweep in Prozent. Der gemessene Weg wird um diesen
# Anteil verkuerzt, damit das Pedal am mechanischen Anschlag zuverlaessig
# 100 Prozent erreicht und nicht bei 98 haengen bleibt.
SWEEP_MARGIN_PCT = 2.0

# Startwert fuer die Waegezelle, bevor zum ersten Mal kalibriert wurde.
HX711_MAX_DEFAULT = 50000

# ---------------------------------------------------------------------------
# Rumble - neu in v9.7
# ---------------------------------------------------------------------------

# Je Kanal (IN1, IN2) am DRV8871.
#
# WICHTIG: Beide Pins eines Kanals muessen auf derselben PWM-Einheit des RP2040
# liegen, sonst funktioniert die Ansteuerung im unteren Bereich schlecht. Das
# ist genau dann der Fall, wenn der erste Pin gerade ist und der zweite direkt
# darauf folgt: GP4/GP5, GP6/GP7, GP8/GP9, ...
RUMBLE_PINS  = [("GP4", "GP5"), ("GP6", "GP7")]
RUMBLE_NAMEN = ["Bremse", "Gas"]

# Gemessene Spannung am Treiber und Nennspannung der Motoren. Ist die
# Versorgung hoeher, deckelt die Firmware das Duty so, dass der Motor im Mittel
# nur seine Nennspannung sieht. Bei gleichen Werten gibt es keinen Deckel.
RUMBLE_VERSORGUNG = 15.0
RUMBLE_MOTOR_NENN = 12.0

RUMBLE_PWM_HZ   = 20000   # ueber dem Hoerbereich
RUMBLE_KICK_MS  = 50      # Anlaufimpuls, nur unterhalb der Losbrechschwelle
RUMBLE_BREMS_MS = 80      # aktives Bremsen beim Abschalten

# Startwert fuer "Brems ms" im Rumble-Tab. Ab dann steht der Wert je Kanal in
# rumble.json und wird hier nicht mehr gelesen.
#
# Er sagt, wie lange eine Nullphase ausgelaufen wird, bevor aktiv gestoppt
# wird - ein Charakterregler, kein Stellwert fuer die Staerke:
#
#   0 ms   Jeder Impuls wird sofort gestoppt. Die Schlaege sind klar
#          voneinander getrennt. Fuer ABS, Randsteine, Schaltruck.
#   hoch   Kurze Luecken laufen aus, aufeinanderfolgende Impulse verschmelzen
#          zu durchgehender Vibration. Fuer Fahrbahn und Radschlupf.
RUMBLE_BREMS_VERZUG_MS = 0

# Namen, unter denen SimHub die Effektstaerken schickt - Reihenfolge wie
# RUMBLE_PINS. Frei waehlbar, muessen nur zur Formel in SimHub passen.
TELE_NAMEN = ["bremse", "gas"]

# Wertebereich, den SimHub schickt. 100 = Prozent (0..100), 1 = Anteil (0..1).
TELE_MAX = 100.0

# Kommt so lange nichts Neues, gelten die Werte als ungueltig und die Motoren
# gehen aus. Verhindert, dass ein Motor weiterlaeuft, wenn SimHub abstuerzt.
TELE_TIMEOUT = 2.0

# Gleitender Mittelwert ueber N Wandlungen der Waegezelle.
#
# Braucht man, sobald ein Rumble-Motor am Bremspad sitzt: der HX711 tastet mit
# 80 Hz ab, der Motor rappelt mit rund 50 Hz, und die Differenz faltet sich als
# 30-Hz-Zappeln in den Bremswert. 8 Messungen lassen rund 10 Hz durch - fuer
# einen Fuss, der mit vielleicht 3 Hz dosiert, mehr als genug.
# 1 schaltet den Filter ab.
HX_FILTER = 8

# HID auch senden, waehrend der Access Point laeuft. In v8 waren die Pedale
# im WLAN-Modus tot. Auf False setzen, wenn beim Kalibrieren keine Achswerte
# ins Spiel gelangen sollen.
HID_IM_WLAN = True
