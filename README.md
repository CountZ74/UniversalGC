# UniversalGC

Universelle Gamecontroller-Firmware für CircuitPython, nach dem Vorbild von FreeJoy:
**Pedale, Buttonbox, Lenkrad, Flugsim-Panel, Arcade-Stick** – was an welchem Pin hängt,
steht in `device.json` und wird über die Weboberfläche des Geräts eingestellt.

Entstanden aus zwei Einzel-Firmwares, die damit abgelöst werden:
[sim-pedale](https://github.com/CountZ74/sim-pedale) (Pedale v9.9) und die Buttonbox v2.1.
Deren am Aufbau ausgemessene Feinheiten – Wraparound-Kalibrierung, Wägezelle über PIO,
Rumble im slow-decay-Verfahren, Logikbuttons – sind übernommen. Verweise wie
„Pedale v9.4“ in Kommentaren beziehen sich auf die Versionsgeschichte dort.

## Was geht

| Funktion | Details |
|---|---|
| Taster | direkt gegen GND, Betriebsart *normal*, *Impuls* (Kippschalter → Tastendruck bei jeder Änderung) oder *Umschalter*, optional Öffner |
| Tastenmatrix | beliebig viele Zeilen × Spalten, mit Dioden (Richtung wählbar) |
| Schieberegister | 74HC165-Ketten, je 8 Eingänge, für viele Tasten an wenigen Pins |
| Encoder | je Raste ein Tastendruck rechts/links, schnelles Drehen wird gepuffert; oder als Achse |
| Achsen (16 bit) | Poti/Hall, AS5600 (Wraparound), Wägezelle HX711 (PIO auf dem Pico), Encoder |
| HID-Achsen | X, Y, Z, Rx, Ry, Rz, Slider, Dial – oder Simulation Controls: Gas, Bremse, Kupplung, Lenkung, Schubhebel, Seitenruder, Fußbremse, Quer-/Höhenruder, Kollektiv |
| Kennlinien | je Achse im Browser zeichnen |
| Logikbuttons | `AND(b9,b10,NOT(motor))`, `GT(rpm,7000)`, `GT(a0,90)` … mit SimHub-Telemetrie |
| LEDs | Dauerlicht/Blinken per Logikausdruck |
| WS2812 | Drehzahlband mit Schaltblitz, Regeln für Pit-Limiter, Flaggen usw. |
| Rumble | DRV8871 mit Totmannschaltung und Not-Aus, Effekte aus SimHub ShakeIt |
| Bluetooth LE | nur ESP32-S3 (siehe unten) |
| Sicherheitsnetz | Pins werden vor dem Speichern geprüft, alte Belegung bleibt als Sicherung; startet die neue zweimal nicht, kommt die alte zurück |

## Geplant

Für allgemeine Gamecontroller (siehe Issues): mittenzentrierte Achsen für Joysticks und
Thumbsticks, Hat-Switch/POV, Shift-Ebene, Ausgabe als Tastatur/Maus.

## Simulation Controls oder Rx/Ry/Rz?

Jede Achse kann sich als normale Joystick-Achse (X … Rz, Slider) oder als
*Simulation Control* melden (`"usage": "brake"` usw., im Browser „Sim: Bremse“). Letzteres
beschreibt Pedale und Lenkrad treffender, aber nicht jedes Spiel wertet diese Achsen aus,
und Windows ordnet sie anders zu. Vorgabe in den Vorlagen bleibt deshalb Rx/Ry/Rz – das
läuft nachweislich. Zum Ausprobieren die HID-Achse im Browser umstellen, speichern, im
Spiel testen; bei Problemen zurückstellen. Wie bei jeder Änderung am Aufbau die Achsen im
Spiel danach neu zuordnen.

**Linux** kennt von den Simulation Controls nur Gas, Bremse, Lenkung, Schubhebel und
Seitenruder. Kupplung, Fußbremse, Quer-/Höhenruder und Kollektiv lässt der Kernel ohne
Meldung weg – die Achse fehlt dann einfach. Unter Linux die Kupplung deshalb als Rz oder
Slider melden.

## Welcher Chip?

| Board | USB-Joystick | Bluetooth | Einsatz |
|---|---|---|---|
| Raspberry Pi Pico W / Pico 2 W | ja | nein (unter CircuitPython kein BLE) | Pedale, Buttonbox |
| **ESP32-S3** (z. B. DevKitC-1, QT Py ESP32-S3) | ja | **ja** | Lenkrad |
| ESP32 ohne Zusatz, ESP32-C3 | nein | ja | ungeeignet |

Beim ESP32-S3 beachten:
- Bluetooth-Verzögerung bestimmt der PC über das Verbindungsintervall (Linux: oft
  30–50 ms). Kürzer unter Linux, gilt bis zum Neustart, danach neu verbinden:
  `sudo sh -c 'echo 6 > /sys/kernel/debug/bluetooth/hci0/conn_min_interval'`
  (6 × 1,25 ms = 7,5 ms). Das Gerät fragt das selbst nicht an – CircuitPython hängt
  dabei, wenn der PC nicht antwortet.
- Der Web-Installer von circuitpython.org fragt nach dem Heim-WLAN und schreibt es in
  `settings.toml`. **Diese Zeilen (`CIRCUITPY_WIFI_SSID`, `CIRCUITPY_WIFI_PASSWORD`,
  `CIRCUITPY_WEB_API_PASSWORD`) auskommentieren** – sonst verbindet sich CircuitPython
  selbst, belegt mit seinem Web-Editor Port 80, und der Access Point von UniversalGC
  startet nicht.
- Analog nur an **GPIO1–10** zuverlässig. GPIO11–20 (ADC2) messen nicht, solange das WLAN
  an ist – die Firmware weist darauf hin.
- GPIO19/20 sind USB, GPIO26–37 hängen meist am Flash/PSRAM – werden gesperrt.
- **GPIO0 nicht als Konfigurationstaster** nehmen: gedrückt beim Einstecken startet der
  ROM-Bootloader.
- Keine PIO – eine Wägezelle läuft dort über Bit-Banging (langsamer).
- Zu wenig USB-Endpunkte für einen zweiten COM-Port: Der ESP32-S3 kann nur 4 IN-Endpunkte
  gleichzeitig nutzen, Konsole + Datenkanal + Joystick bräuchten 5 (CircuitPython ginge in
  den abgesicherten Modus). Die Telemetrie läuft dort deshalb über den **einen** COM-Port
  (die Konsole) – in SimHub diesen Port eintragen.

## Installation

1. CircuitPython auf das Board spielen (https://circuitpython.org/downloads).
2. **Release-Paket** von der Releases-Seite laden (`UniversalGC-<version>-cp10.zip` für
   CircuitPython 10.x) und entpacken. Darin sind die Module vorkompiliert – das spart auf
   dem Pico W spürbar Speicher – und die nötigen Bibliotheken.
3. Installieren:
   ```bash
   python3 installieren.py lenkrad      # mit Vorlage als device.json
   python3 installieren.py              # nur aktualisieren, Belegung bleibt
   python3 installieren.py --liste      # Vorlagen anzeigen
   ```
   Das Skript findet `CIRCUITPY` selbst (Linux, macOS, Windows), kopiert in der richtigen
   Reihenfolge (`boot.py` zuletzt), entfernt veraltete Dateien, holt fehlende Bibliotheken
   selbst aus dem offiziellen Adafruit-Bundle passend zur CircuitPython-Version (wird in
   `~/.cache/universalgc` zwischengespeichert; ohne Internet notfalls
   [circup](https://github.com/adafruit/circup) oder `--bundle ZIP`) und schreibt alles
   durch, bevor es „Fertig“ meldet. Dasselbe Skript funktioniert auch direkt im
   Quelltext-Repo (`UniversalGC-main`).
4. Laufwerk **auswerfen**, abziehen, neu einstecken.

**Update eines Boards im Normalbetrieb** (Laufwerk aus): einfach `python3 installieren.py`.
Ist `pyserial` installiert, sucht das Skript das Board über seinen
COM-Port, schickt es in den Wartungsmodus, wartet auf `CIRCUITPY` und installiert. Thonny
dabei schließen – es belegt den Port. Bei mehreren Boards fragt das Skript nach; mit
`--seriell` geht das auch, wenn schon ein anderes Laufwerk sichtbar ist. Ohne `pyserial`
oder bei alter Firmware: Wartungsmodus von Hand (Konfigurationstaster beim Einstecken
halten oder Weboberfläche → „Neustart mit Laufwerk“).

`pyserial` und `circup` installieren:

| System | pyserial | circup |
|---|---|---|
| Arch / Manjaro | `sudo pacman -S python-pyserial` | `pipx install circup` (meist nicht nötig) |
| Debian / Ubuntu | `sudo apt install python3-serial` | `pipx install circup` |
| Windows / macOS | `pip install pyserial` | `pip install circup` |

Unter Linux muss der Benutzer die seriellen Ports benutzen dürfen: Gruppe `uucp`
(Arch) bzw. `dialout` (Debian/Ubuntu), z. B. `sudo usermod -aG uucp $USER`, danach neu
anmelden.

Ohne Python geht es auch von Hand: den Inhalt des Pakets auf `CIRCUITPY` kopieren,
`boot.py` zuletzt, auswerfen. Alte `.py`-Module der Firmware im Hauptverzeichnis vorher
löschen – sie verdecken die neuen `.mpy` in `lib/`.

Fehlt beim Start noch eine Pflichtdatei, lässt `boot.py` das Laufwerk an (in
`boot_out.txt` steht, was fehlt). Ohne `device.json` oder ohne Konfigurationstaster
bleibt `CIRCUITPY` ebenfalls sichtbar (Einrichtungsmodus). Das Gerät meldet sich dann mit
8 leeren Buttons, startet den Access Point von selbst (WLAN `UniversalGC-Setup`, Passwort
`universalgc`) und zeigt im Browser die Vorlagen an.

### Paket selbst bauen

```bash
python3 werkzeuge/paket.py --mpy-cross PFAD/ZU/mpy-cross [--bundle adafruit-…-10.x-mpy-….zip]
```
`mpy-cross` muss von **CircuitPython** stammen (nicht von MicroPython) und zur
Hauptversion auf dem Board passen; gebaut wird er im CircuitPython-Quelltext mit
`make -C mpy-cross`. GitHub baut das Paket bei jedem Push automatisch
(`.github/workflows/paket.yml`) und hängt es bei einem Tag `v…` an ein Release.

### Bibliotheken (`lib/`)

Das Release-Paket enthält sie, `installieren.py` kopiert nur die, die die Belegung
braucht (sonst holt es sie über circup). Von Hand: aus dem Adafruit-Bundle passend zur
CircuitPython-Version:

| Wofür | Datei/Ordner |
|---|---|
| Wägezelle über PIO (Pico) | `adafruit_pioasm.mpy` |
| Wägezelle über Bit-Banging (ESP32-S3) | `adafruit_hx711/` |
| WS2812 | `neopixel.mpy` |
| Bluetooth (ESP32-S3) | `adafruit_ble/` |

Taster, Matrix, Schieberegister und Encoder brauchen nichts – `keypad` und `rotaryio`
sind eingebaut.

**Speicher:** Auf dem Pico W wird es mit WLAN, vielen Achsen und WS2812 eng – dann das
Release-Paket mit den vorkompilierten Modulen benutzen. Die Statusseite zeigt den freien
Speicher.

## Bedienung

- **Konfigurationstaster kurz drücken:** WLAN-Access-Point an/aus. Mit dem Handy
  verbinden, `http://192.168.4.1` öffnen. Der Taster ist zugleich Not-Aus für die
  Rumble-Motoren.
- **Wartungsmodus:** Konfigurationstaster beim Einstecken gedrückt halten → `CIRCUITPY`
  bleibt als Laufwerk sichtbar, dafür kann das Gerät nicht speichern.
- **Speichern bei sichtbarem Laufwerk:** Ist `CIRCUITPY` gerade für den PC freigegeben
  (Wartung, Einrichtung oder nach dem Kopieren noch kein echter Neustart), wartet die
  neue Belegung im NVM. Das Gerät startet neu, meldet sich gleich mit ihr an und
  schreibt sie als `device.json`. Dafür braucht die neue Belegung einen
  Konfigurationstaster oder eine Tastenkombination.
- **Tastenkombination statt Konfigurationstaster:** unter *Belegung* →
  *Tastenkombination* Buttonnummern eintragen (z. B. `1, 2`), in `device.json`:
  `"config_combo": {"buttons": [1, 2], "hold": 3}`. Alle gemeinsam `hold` Sekunden
  halten schaltet den Access Point an/aus. Erlaubt sind Taster, Matrix- und
  Schieberegister-Eingänge; die Buttons gehen dabei auch an den PC, also eine
  Kombination wählen, die im Spiel nichts anrichtet. Beim Einstecken gehalten
  öffnet sie den Wartungsmodus – das geht nur mit direkt angeschlossenen Tastern,
  sonst über *Wartung* in der Weboberfläche oder `installieren.py --seriell`.
- **Belegung ändern:** Tab *Belegung* → *Prüfen* → *Speichern & Neustart*. Der PC liest
  den Aufbau nur beim Einstecken, deshalb der Neustart.
  Neue Buttonnummern oder Achsen müssen im Spiel einmal neu zugeordnet werden.
- **Poti-Achsen:** Glättung (`smooth`, Standard 3) und Hysterese (`hyst`, Standard
  0,5 %) halten rauschende Potis in Ruhe still. Mit **Mittelstellung** (`center`)
  liegen 50 % in der Mitte, die Totzone wirkt um die Mitte – für Drehregler mit
  Raste, Trimmung oder Hall-Sticks. Kalibrieren: Mitte setzen, dann bis zu beiden
  Anschlägen drehen.
- **AS5600 als Encoder:** Statt eines Drehencoders (Pins A und B) geht ein AS5600 hinter
  einem Knopf mit Rasten, z. B. gedruckt: 1 Analogpin (`OUT`), berührungslos, prellt
  nicht. Unter *Belegung → Encoder* Typ „AS5600 + Rastenknopf“ und die Rastenzahl je
  Umdrehung eintragen. Wie beim Drehencoder gibt jede Raste einen Impuls auf „rechts“
  bzw. „links“. Beim Einschalten muss der Knopf in einer Raste stehen.
- **Stufenschalter:** Drehschalter mit festen Stellungen an *einem* Analogpin – je
  Stellung ein Button, immer genau einer gedrückt. Entweder ein AS5600 hinter einem
  Rastenknopf (Abstand der Stellungen in Grad, Stellung 1 per „Aktuelle Stellung als
  Stellung 1“ übernehmen; füllen die Stellungen den ganzen Kreis, geht es von der
  letzten zur ersten weiter) oder ein normaler Drehschalter mit Widerstandskette
  (gleiche Widerstände zwischen den Kontakten, Enden an GND und 3,3 V).
- **Buttonnummern festhalten:** Jede Quelle (Taster, Matrix, Schieberegister, Encoder,
  Logik) kann ihre erste Nummer mit `btn` festlegen. So bleiben die Zuordnungen im Spiel
  gültig, wenn später etwas dazukommt.

### Pin-Suche

Im Tab *Belegung* findet die **Pin-Suche** heraus, was wo angeschlossen ist:

1. **„Taster & Encoder suchen“** – jeden Taster einmal drücken, jeden Encoder ein paar
   Rasten drehen, Kippschalter umlegen. Erkannt wird: Taster, gehaltener Schalter (wird als
   „Impuls“ vorgeschlagen), Encoder (zwei Pins, die abwechselnd schalten).
2. **„Achsen suchen“** – Potis und Hall-Wippen ganz durchbewegen. In der ersten Sekunde
   lernt die Suche das Grundrauschen, danach meldet sie Pins, die sich deutlich bewegen.
3. Bei jedem Fund **„übernehmen“** (oder bei einem Taster „als Konfig-Taster“), Namen
   anpassen, „Prüfen“, „Speichern & Neustart“.

Beobachtet werden nur freie Pins und nur als Eingang – Ausgänge schaltet die Suche nie.
Strapping-Pins (ESP32-S3: GPIO0, 3, 45, 46), USB- und Flash-Pins bleiben außen vor. LEDs,
WS2812, Rumble-Motoren, Wägezellen und Tastenmatrix lassen sich nicht erkennen und werden
von Hand eingetragen. Die Suche endet nach 5 Minuten von selbst.

### Wartungsmodus ohne Taster

Thonny lädt bei CircuitPython über das Laufwerk `CIRCUITPY` hoch – im Normalbetrieb ist es
aus. Ohne den Konfigurationstaster zu drücken geht es so:

- Weboberfläche, Tab *Status*: **Neustart mit Laufwerk CIRCUITPY**, oder
- in der Thonny-Shell (Strg+C, dann):
  ```python
  import merker; merker.wartung()
  ```

Das Gerät startet einmalig mit sichtbarem Laufwerk. Beim nächsten Einstecken ist alles
wieder normal.

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
| `lenkrad.json` | 2 Schaltwippen, 4×4-Matrix, 2 Encoder, 2 Kupplungswippen (Hall), 10 WS2812, Bluetooth | ESP32-S3 (DevKitC-1, YD-ESP32-S3 …) | 0x4713 |

Die Pins im Lenkrad sind ein Vorschlag – beim Verdrahten an das eigene Board anpassen.

**Pinnamen:** Derselbe Chip-Pin heißt je nach Board `IO21` (Espressif DevKitC-1), `GPIO21`
(YD-ESP32-S3 und viele andere) oder `GP21` (Pico). Die Firmware probiert die anderen
Schreibweisen von selbst, wenn das Board einen Namen nicht kennt – die Vorlagen passen
deshalb auf jedes Board. Welche Namen ein Board hat, zeigt in der Thonny-Shell
`import board; print(dir(board))`.

### Umstieg von den alten Firmwares

`installieren.py` erkennt die alte Pedal-Firmware (v9) und die Buttonbox (v2) und
übernimmt sie:

1. Wartungsmodus von Hand – die alten Firmwares können das noch nicht über die Konsole:
   Taster beim Einstecken halten (Pedale **GP3**, Buttonbox **GP15**).
2. `python3 installieren.py` – eine Vorlage braucht es nicht.

Übernommen wird:
- **Belegung** aus der alten `settings.py`: Pins, WLAN-Name und -Passwort, Rumble-Pins,
  -Namen und SimHub-Namen, Totzone, Filter …
- **USB-PID, Gerätetyp und HID-Achsen** aus der alten `boot.py` – die Achsen heißen im
  Spiel wie bisher (v9.7: Gamepad X/Y/Z, v9.9: Joystick Rx/Ry/Rz, Buttonbox: Gamepad
  Rx/Ry/Rz, Buttons 1–11, Logik ab 23).
- **Kalibrierung** der Pedale (auch Kennlinien) und der Buttonbox-Achsen, **Logikbuttons,
  unterdrückte Inputs und LED-Logik** der Buttonbox. `rumble.json` bleibt, wie es ist.
- Die alten Dateien landen in **`alt/`** auf dem Board. Zurück zur alten Firmware: deren
  Dateien aus `alt/` wieder ins Hauptverzeichnis kopieren und die neuen löschen.

Mit `--keine-uebernahme` nimmt das Skript stattdessen die angegebene Vorlage.

## Telemetrie (SimHub & Co.)

Das Gerät nimmt über seinen **zweiten** COM-Port (Datenkanal; beim ESP32-S3 über den
einzigen COM-Port) Zeilen der Form
`name=wert;name=wert` mit `\n` am Ende an – von SimHub, einem eigenen Skript oder jedem
anderen Programm. In SimHub dafür ein *Custom Serial Device* auf diesen Port legen. Die
Namen sind frei und gelten überall: in Logikausdrücken, in LED-Regeln, für Rumble und Drehzahlband.

Für das Drehzahlband am Lenkrad braucht es z. B. `rpm`, `rpmmax` und `pit`. In SimHub als
NCalc-Formel sinngemäß:

```
'rpm=' + [Rpms] + ';rpmmax=' + [CarSettings_MaxRPM] + ';pit=' + [PitLimiterOn] + '\n'
```

(Die Property-Namen in SimHub nachschlagen – sie unterscheiden sich je nach Version.)

## Tests auf dem PC

```
python3 tests/test_firmware.py     # Logik, Descriptor, Pins, Kalibrierung, Installer …
python3 tests/sim.py buttonbox     # ganzes Gerät simuliert, http://localhost:8765
```

Der Simulator ersetzt die CircuitPython-Module durch Nachbauten und das Laufwerk durch
ein temporäres Verzeichnis. Die Weboberfläche läuft echt, ein Neustart nach dem
Speichern startet den Prozess mit `boot.py` neu. `hid_fehler.txt` im Simulationsordner
meldet Reports, deren Länge nicht zum Descriptor passt.

## Lizenz

UniversalGC steht unter der **GNU General Public License v3.0 oder neuer** (siehe
[`LICENSE`](LICENSE)). Nutzen, ändern und weitergeben ist erlaubt, auch kommerziell –
wer die Firmware aber weitergibt, etwa auf verkauften Geräten, muss den vollständigen
Quellcode seiner Version unter derselben Lizenz mitliefern.
