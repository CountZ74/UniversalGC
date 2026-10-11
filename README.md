# Universelle SimRacing-Firmware

Eine CircuitPython-Firmware für **Pedale, Buttonbox und Lenkrad** nach dem Vorbild von
FreeJoy. Was an welchem Pin hängt, steht in `device.json` und wird über die
Weboberfläche des Geräts eingestellt. Entstanden aus der Pedal-Firmware v9.9 und der
Buttonbox v2.1 – deren am Aufbau ausgemessene Feinheiten (Wraparound-Kalibrierung,
Wägezelle über PIO, Rumble im slow-decay-Verfahren, Logikbuttons) sind übernommen.

## Was geht

| Funktion | Details |
|---|---|
| Taster | direkt gegen GND, Betriebsart *normal*, *Impuls* (Kippschalter → Tastendruck bei jeder Änderung) oder *Umschalter*, optional Öffner |
| Tastenmatrix | beliebig viele Zeilen × Spalten, mit Dioden (Richtung wählbar) |
| Schieberegister | 74HC165-Ketten, je 8 Eingänge, für viele Tasten an wenigen Pins |
| Encoder | je Raste ein Tastendruck rechts/links, schnelles Drehen wird gepuffert; oder als Achse |
| Achsen (16 bit) | Poti/Hall, AS5600 (Wraparound), Wägezelle HX711 (PIO auf dem Pico), Encoder |
| Kennlinien | je Achse im Browser zeichnen |
| Logikbuttons | `AND(b9,b10,NOT(motor))`, `GT(rpm,7000)`, `GT(a0,90)` … mit SimHub-Telemetrie |
| LEDs | Dauerlicht/Blinken per Logikausdruck |
| WS2812 | Drehzahlband mit Schaltblitz, Regeln für Pit-Limiter, Flaggen usw. |
| Rumble | DRV8871 mit Totmannschaltung und Not-Aus, Effekte aus SimHub ShakeIt |
| Bluetooth LE | nur ESP32-S3 (siehe unten) |
| Sicherheitsnetz | Pins werden vor dem Speichern geprüft, alte Belegung bleibt als Sicherung; startet die neue zweimal nicht, kommt die alte zurück |

## Welcher Chip?

| Board | USB-Joystick | Bluetooth | Einsatz |
|---|---|---|---|
| Raspberry Pi Pico W / Pico 2 W | ja | nein (unter CircuitPython kein BLE) | Pedale, Buttonbox |
| **ESP32-S3** (z. B. DevKitC-1, QT Py ESP32-S3) | ja | **ja** | Lenkrad |
| ESP32 ohne Zusatz, ESP32-C3 | nein | ja | ungeeignet |

Beim ESP32-S3 beachten:
- Analog nur an **GPIO1–10** zuverlässig. GPIO11–20 (ADC2) messen nicht, solange das WLAN
  an ist – die Firmware weist darauf hin.
- GPIO19/20 sind USB, GPIO26–37 hängen meist am Flash/PSRAM – werden gesperrt.
- **GPIO0 nicht als Konfigurationstaster** nehmen: gedrückt beim Einstecken startet der
  ROM-Bootloader.
- Keine PIO – eine Wägezelle läuft dort über Bit-Banging (langsamer).

## Installation

1. CircuitPython auf das Board spielen (https://circuitpython.org/downloads).
2. Auf `CIRCUITPY` kopieren:
   ```
   boot.py code.py cfg.py pins.py eingaben.py achsen.py kalib.py logik.py
   tele.py rumble.py leds.py ble_hid.py web.py index.html
   presets/          (Ordner)
   device.json       Kopie der passenden Vorlage aus presets/
   lib/              siehe unten
   ```
3. Neu einstecken. Ab jetzt ist `CIRCUITPY` nicht mehr als Laufwerk sichtbar – das Gerät
   braucht es selbst zum Speichern (siehe *Wartungsmodus*).

Ohne `device.json` startet das Gerät mit 8 leeren Buttons und schaltet den Access Point
**von selbst** ein (WLAN `SimRacing-Setup`, Passwort `simracing`). Dann im Browser unter
*Belegung* eine Vorlage laden, anpassen, speichern.

### Bibliotheken (`lib/`)

Aus dem Adafruit-Bundle passend zur CircuitPython-Version, nur was gebraucht wird:

| Wofür | Datei/Ordner |
|---|---|
| Wägezelle über PIO (Pico) | `adafruit_pioasm.mpy` |
| Wägezelle über Bit-Banging (ESP32-S3) | `adafruit_hx711/` |
| WS2812 | `neopixel.mpy` |
| Bluetooth (ESP32-S3) | `adafruit_ble/` |

Taster, Matrix, Schieberegister und Encoder brauchen nichts – `keypad` und `rotaryio`
sind eingebaut.

**Speicher:** Auf dem Pico W wird es mit WLAN, vielen Achsen und WS2812 eng. Dann die
`.py`-Module (alle außer `boot.py` und `code.py`) mit `mpy-cross` zu `.mpy` übersetzen –
das spart beim Laden viel RAM. Die Statusseite zeigt den freien Speicher.

## Bedienung

- **Konfigurationstaster kurz drücken:** WLAN-Access-Point an/aus. Mit dem Handy
  verbinden, `http://192.168.4.1` öffnen. Der Taster ist zugleich Not-Aus für die
  Rumble-Motoren.
- **Wartungsmodus:** Konfigurationstaster beim Einstecken gedrückt halten → `CIRCUITPY`
  bleibt als Laufwerk sichtbar, dafür kann das Gerät nicht speichern.
- **Belegung ändern:** Tab *Belegung* → *Prüfen* → *Speichern & Neustart*. Der PC liest
  den Aufbau nur beim Einstecken, deshalb der Neustart.
  Neue Buttonnummern oder Achsen müssen im Spiel einmal neu zugeordnet werden.
- **Buttonnummern festhalten:** Jede Quelle (Taster, Matrix, Schieberegister, Encoder,
  Logik) kann ihre erste Nummer mit `btn` festlegen. So bleiben die Zuordnungen im Spiel
  gültig, wenn später etwas dazukommt.

### Rückfall

Beim Speichern bleibt die alte Belegung als `device.bak.json` liegen und `cfg_pending`
wird angelegt. Läuft das Gerät danach 15 Sekunden sauber, wird die Markierung gelöscht.
Scheitert der Start zweimal hintereinander, holt `boot.py` die alte Belegung zurück. Der
Grund steht in `fehler.txt` bzw. `boot_out.txt`.

## Vorlagen

| Datei | Gerät | Board | USB-PID |
|---|---|---|---|
| `pedale.json` | 3 Pedale: AS5600 Gas/Kupplung, Wägezelle Bremse, 2 Rumble-Motoren – wie Pedale v9.9 | Pico W | 0x4712 |
| `buttonbox.json` | 11 Taster/Schalter, 3 Potis, 16 Logikbuttons ab 23, Anlasser-LED – Buttonnummern wie Buttonbox v2.1 | Pico 2 W | 0x4711 |
| `lenkrad.json` | 2 Schaltwippen, 4×4-Matrix, 2 Encoder, 2 Kupplungswippen (Hall), 10 WS2812, Bluetooth | ESP32-S3 DevKitC | 0x4713 |

Die Pins im Lenkrad sind ein Vorschlag – beim Verdrahten an das eigene Board anpassen.

### Umstieg von den alten Firmwares

- **Pedale:** Achsen und Gerätetyp (Joystick, Rx/Ry/Rz, keine Buttons) sind wie in v9.9.
  Die Kalibrierung muss einmal neu gemacht werden (neues Dateiformat). Rumble-Werte im
  Tab *Rumble* neu eintragen.
- **Buttonbox:** Buttons 1–11 und Logikbuttons 23–38 liegen wie in v2.1, Gerätetyp bleibt
  *Gamepad*. Logikausdrücke und LED-Logik einmal im Browser neu eintragen.

## SimHub

Wie bisher: In SimHub ein *Custom Serial Device* auf den **zweiten** COM-Port des Geräts
(der Datenkanal), Format eine Zeile `name=wert;name=wert` mit `\n` am Ende. Die Namen sind
frei und gelten überall: in Logikausdrücken, in LED-Regeln, für Rumble und Drehzahlband.

Für das Drehzahlband am Lenkrad braucht es z. B. `rpm`, `rpmmax` und `pit`. In SimHub als
NCalc-Formel sinngemäß:

```
'rpm=' + [Rpms] + ';rpmmax=' + [CarSettings_MaxRPM] + ';pit=' + [PitLimiterOn] + '\n'
```

(Die Property-Namen in SimHub nachschlagen – sie unterscheiden sich je nach Version.)

## Tests auf dem PC

```
python3 firmware/tests/test_firmware.py     # Logik, Descriptor, Pins, Kalibrierung …
python3 firmware/tests/sim.py buttonbox     # ganzes Gerät simuliert, http://localhost:8765
```

Der Simulator ersetzt die CircuitPython-Module durch Nachbauten und das Laufwerk durch
ein temporäres Verzeichnis. Die Weboberfläche läuft echt, ein Neustart nach dem
Speichern startet den Prozess mit `boot.py` neu. `hid_fehler.txt` im Simulationsordner
meldet Reports, deren Länge nicht zum Descriptor passt.
