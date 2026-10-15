#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""UniversalGC auf ein Board mit CircuitPython installieren oder aktualisieren.

    python3 installieren.py                  aktualisieren, Belegung bleibt
    python3 installieren.py lenkrad          zusaetzlich Vorlage als device.json,
                                             falls noch keine da ist
    python3 installieren.py --liste          Vorlagen anzeigen
    python3 installieren.py --trocken        nur zeigen, was passieren wuerde

Optionen:
    --ziel PFAD          Laufwerk CIRCUITPY (sonst automatisch gesucht)
    --ueberschreiben     vorhandene device.json durch die Vorlage ersetzen

Laeuft mit Python 3 auf Linux, macOS und Windows, ohne Zusatzpakete. Das
Skript arbeitet sowohl im Quelltext-Repo (Module als .py) als auch in einem
entpackten Release-Paket (Module vorkompiliert als .mpy in lib/).

Was es tut:
  1. CIRCUITPY finden und boot_out.txt lesen (Board, CircuitPython-Version)
  2. die Firmware kopieren - boot.py ganz zuletzt, damit das Laufwerk nicht
     abgeschaltet wird, bevor alles drauf ist
  3. veraltete Doppel entfernen (eine alte cfg.py im Hauptverzeichnis wuerde
     sonst die neue lib/cfg.mpy verdecken)
  4. die noetigen Bibliotheken: aus dem Paket, sonst ueber circup
  5. jede Datei auf das Laufwerk durchschreiben (fsync, sync) - ein halb
     geschriebenes CIRCUITPY ist die haeufigste Ursache fuer Muell in Dateien

Das Laufwerk muss sichtbar sein: bei einem frischen Board ist es das, sonst
im Wartungsmodus (Konfigurationstaster beim Einstecken halten, oder in der
Weboberflaeche "Neustart mit Laufwerk").
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HIER = os.path.dirname(os.path.abspath(__file__))

# Module der Firmware (ohne Endung). boot.py und code.py bleiben immer .py.
MODULE = ("app", "cfg", "merker", "pins", "eingaben", "achsen", "kalib",
          "logik", "tele", "rumble", "leds", "ble_hid", "web", "suche")

# Bibliotheken aus dem Adafruit-Bundle: Name im Bundle -> Ordner/Datei in lib/
BIBLIOTHEKEN = {
    "neopixel": "neopixel.mpy",
    "adafruit_ble": "adafruit_ble",
    "adafruit_pioasm": "adafruit_pioasm.mpy",
    "adafruit_hx711": "adafruit_hx711",
}


# --- reine Hilfsfunktionen (getestet in tests/test_firmware.py) -------------

def boot_out_lesen(text):
    """(CircuitPython-Version, Board-ID, Chip) aus boot_out.txt."""
    version = board = chip = None
    m = re.search(r"CircuitPython (\d+\.\d+\.\d+\S*)", text)
    if m:
        version = m.group(1)
    m = re.search(r"Board ID:\s*(\S+)", text)
    if m:
        board = m.group(1)
    erste = text.splitlines()[0].lower() if text else ""
    if "esp32s3" in erste or "esp32-s3" in erste:
        chip = "esp32s3"
    elif "rp2350" in erste:
        chip = "rp2350"
    elif "rp2040" in erste:
        chip = "rp2040"
    return version, board, chip


def noetige_bibliotheken(c, chip):
    """Welche Bibliotheken die Belegung braucht."""
    libs = []
    if not isinstance(c, dict):
        return libs
    px = c.get("pixels")
    if isinstance(px, dict) and px.get("pin"):
        libs.append("neopixel")
    ble = c.get("ble")
    if isinstance(ble, dict) and ble.get("enabled"):
        libs.append("adafruit_ble")
    for a in c.get("axes") or []:
        if isinstance(a, dict) and a.get("type") == "hx711":
            if chip == "esp32s3" or a.get("mode") == "bitbang":
                libs.append("adafruit_hx711")
            else:
                libs.append("adafruit_pioasm")
                # Rueckfall, falls PIO nicht klappt
                libs.append("adafruit_hx711")
    out = []
    for name in libs:
        if name not in out:
            out.append(name)
    return out


def paket_art(quelle):
    """'paket' (vorkompiliert, Module in lib/) oder 'quelltext'."""
    if os.path.exists(os.path.join(quelle, "lib", "app.mpy")):
        return "paket"
    if os.path.exists(os.path.join(quelle, "app.py")):
        return "quelltext"
    return None


def plan(quelle, art):
    """Liste (quellpfad, zielpfad relativ) in Kopierreihenfolge, plus Liste
    der Zieldateien, die als veraltete Doppel geloescht werden."""
    kopieren = []
    loeschen = []
    if art == "paket":
        for m in MODULE:
            kopieren.append((os.path.join(quelle, "lib", m + ".mpy"),
                             "lib/%s.mpy" % m))
            loeschen.append("%s.py" % m)       # wuerde die .mpy verdecken
            loeschen.append("%s.mpy" % m)
    else:
        for m in MODULE:
            kopieren.append((os.path.join(quelle, m + ".py"), "%s.py" % m))
            loeschen.append("lib/%s.mpy" % m)
            loeschen.append("%s.mpy" % m)
    kopieren.append((os.path.join(quelle, "index.html"), "index.html"))
    pdir = os.path.join(quelle, "presets")
    for n in sorted(os.listdir(pdir)):
        if n.endswith(".json"):
            kopieren.append((os.path.join(pdir, n), "presets/" + n))
    kopieren.append((os.path.join(quelle, "code.py"), "code.py"))
    # boot.py ganz zuletzt: erst wenn alles da ist, darf es das Laufwerk
    # beim naechsten Start abschalten
    kopieren.append((os.path.join(quelle, "boot.py"), "boot.py"))
    return kopieren, loeschen


# --- Laufwerk finden --------------------------------------------------------

def laufwerk_suchen():
    kandidaten = []
    if sys.platform.startswith("win"):
        try:
            import ctypes
            import string
            name = ctypes.create_unicode_buffer(64)
            for b in string.ascii_uppercase:
                wurzel = "%s:\\" % b
                if not os.path.exists(wurzel):
                    continue
                ok = ctypes.windll.kernel32.GetVolumeInformationW(
                    ctypes.c_wchar_p(wurzel), name, 64, None, None, None, None, 0)
                if ok and name.value.upper().startswith("CIRCUITPY"):
                    kandidaten.append(wurzel)
        except Exception:
            pass
    elif sys.platform == "darwin":
        if os.path.isdir("/Volumes"):
            kandidaten += [os.path.join("/Volumes", n) for n in os.listdir("/Volumes")
                           if n.upper().startswith("CIRCUITPY")]
    else:
        try:
            with open("/proc/mounts") as f:
                for zeile in f:
                    teile = zeile.split()
                    if len(teile) > 1:
                        pfad = teile[1].replace("\\040", " ")
                        if os.path.basename(pfad).upper().startswith("CIRCUITPY"):
                            kandidaten.append(pfad)
        except OSError:
            pass
    return [k for k in kandidaten if os.path.exists(os.path.join(k, "boot_out.txt"))
            or os.path.exists(os.path.join(k, "code.py"))
            or os.path.exists(os.path.join(k, "lib"))]


# --- Schreiben --------------------------------------------------------------

def durchschreiben(quelle, ziel):
    """Kopieren und sofort auf das Laufwerk durchschreiben."""
    os.makedirs(os.path.dirname(ziel) or ".", exist_ok=True)
    with open(quelle, "rb") as f:
        daten = f.read()
    with open(ziel, "wb") as f:
        f.write(daten)
        f.flush()
        os.fsync(f.fileno())
    # Zurueckgelesen vergleichen - deckt ein kaputtes Dateisystem sofort auf
    with open(ziel, "rb") as f:
        if f.read() != daten:
            raise IOError("%s: Inhalt nach dem Schreiben falsch - Dateisystem "
                          "beschaedigt? Dann in der Konsole "
                          "storage.erase_filesystem() und neu installieren" % ziel)


def baum_kopieren(quelle, ziel, trocken):
    for wurzel, _, dateien in os.walk(quelle):
        for n in dateien:
            q = os.path.join(wurzel, n)
            z = os.path.join(ziel, os.path.relpath(q, quelle))
            if not trocken:
                durchschreiben(q, z)


def sync():
    if hasattr(os, "sync"):
        os.sync()


# --- Hauptprogramm ----------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="UniversalGC auf CIRCUITPY installieren oder aktualisieren")
    ap.add_argument("vorlage", nargs="?",
                    help="Vorlage aus presets/ als device.json (z.B. lenkrad)")
    ap.add_argument("--ziel", help="Pfad zu CIRCUITPY")
    ap.add_argument("--ueberschreiben", action="store_true",
                    help="vorhandene device.json durch die Vorlage ersetzen")
    ap.add_argument("--trocken", action="store_true",
                    help="nur anzeigen, nichts schreiben")
    ap.add_argument("--liste", action="store_true", help="Vorlagen anzeigen")
    a = ap.parse_args(argv)

    art = paket_art(HIER)
    if art is None:
        print("Hier liegt weder app.py noch lib/app.mpy - das Skript muss im "
              "UniversalGC-Ordner liegen.")
        return 1
    vorlagen = sorted(n[:-5] for n in os.listdir(os.path.join(HIER, "presets"))
                      if n.endswith(".json"))
    if a.liste:
        print("Vorlagen:", ", ".join(vorlagen))
        return 0
    if a.vorlage and a.vorlage not in vorlagen:
        print("Vorlage '%s' gibt es nicht. Vorhanden: %s" % (a.vorlage, ", ".join(vorlagen)))
        return 1

    # Laufwerk
    if a.ziel:
        ziel = a.ziel
    else:
        gefunden = laufwerk_suchen()
        if not gefunden:
            print("Kein Laufwerk CIRCUITPY gefunden.\n"
                  "  - Frisches Board: ist CircuitPython drauf und das Laufwerk eingehaengt?\n"
                  "  - UniversalGC laeuft schon: Wartungsmodus (Konfigurationstaster beim\n"
                  "    Einstecken halten, oder Weboberflaeche -> 'Neustart mit Laufwerk').\n"
                  "  - Oder den Pfad angeben: --ziel /media/NAME/CIRCUITPY")
            return 1
        if len(gefunden) > 1:
            print("Mehrere CIRCUITPY-Laufwerke gefunden, bitte mit --ziel waehlen:")
            for g in gefunden:
                print("   ", g)
            return 1
        ziel = gefunden[0]
    if not os.path.isdir(ziel):
        print("%s ist kein Verzeichnis." % ziel)
        return 1

    # Board
    version = board = chip = None
    try:
        with open(os.path.join(ziel, "boot_out.txt"), errors="replace") as f:
            version, board, chip = boot_out_lesen(f.read())
    except OSError:
        pass
    print("Ziel:     ", ziel)
    print("Board:    ", board or "?", "(%s)" % (chip or "?"))
    print("CircuitPython:", version or "?")
    print("Quelle:   ", "Release-Paket (.mpy)" if art == "paket" else "Quelltext (.py)")

    if art == "paket":
        try:
            with open(os.path.join(HIER, "VERSION")) as f:
                paket = json.load(f)
        except (OSError, ValueError):
            paket = {}
        cp = str(paket.get("circuitpython", ""))
        if version and cp and version.split(".")[0] != cp.split(".")[0]:
            print("\nDieses Paket ist fuer CircuitPython %s.x gebaut, auf dem Board "
                  "laeuft %s.\nDie .mpy-Dateien passen nicht - passendes Paket "
                  "nehmen oder den Quelltext installieren." % (cp, version))
            return 1

    # Belegung
    dj = os.path.join(ziel, "device.json")
    vorhanden = os.path.exists(dj)
    belegung = None
    if a.vorlage and (not vorhanden or a.ueberschreiben):
        with open(os.path.join(HIER, "presets", a.vorlage + ".json")) as f:
            belegung = json.load(f)
        print("Belegung:  Vorlage '%s' wird device.json%s" %
              (a.vorlage, " (ersetzt die vorhandene)" if vorhanden else ""))
    elif vorhanden:
        try:
            with open(dj) as f:
                belegung = json.load(f)
        except (OSError, ValueError):
            belegung = None
        print("Belegung:  vorhandene device.json bleibt"
              + (" (Vorlage ignoriert, --ueberschreiben zum Ersetzen)" if a.vorlage else ""))
    else:
        print("Belegung:  keine device.json - das Geraet startet im Einrichtungsmodus")

    # Platz
    kopieren, loeschen = plan(HIER, art)
    groesse = sum(os.path.getsize(q) for q, _ in kopieren)
    frei = shutil.disk_usage(ziel).free
    if groesse > frei + sum(os.path.getsize(os.path.join(ziel, z))
                            for _, z in kopieren if os.path.exists(os.path.join(ziel, z))):
        print("\nZu wenig Platz auf CIRCUITPY (%d kB noetig, %d kB frei)." %
              (groesse // 1024, frei // 1024))
        return 1

    if a.trocken:
        print("\n--trocken: es wird nichts geschrieben. Geplant:")
        for z in loeschen:
            if os.path.exists(os.path.join(ziel, z)):
                print("  loeschen ", z)
        for _, z in kopieren:
            print("  kopieren ", z)

    # boot.py zuerst entfernen: stuerzt das Kopieren unterwegs ab, laesst
    # das Geraet beim naechsten Start das Laufwerk an
    if not a.trocken and os.path.exists(os.path.join(ziel, "boot.py")):
        os.remove(os.path.join(ziel, "boot.py"))
        sync()

    for z in loeschen:
        p = os.path.join(ziel, z)
        if os.path.exists(p) and not a.trocken:
            os.remove(p)
    if belegung is not None and a.vorlage and (not vorhanden or a.ueberschreiben):
        if not a.trocken:
            durchschreiben(os.path.join(HIER, "presets", a.vorlage + ".json"), dj)

    # Bibliotheken
    libs = noetige_bibliotheken(belegung, chip)
    if libs:
        print("Bibliotheken:", ", ".join(libs))
    fehlende = []
    for name in libs:
        q = os.path.join(HIER, "lib", BIBLIOTHEKEN[name])
        z = os.path.join(ziel, "lib", BIBLIOTHEKEN[name])
        if os.path.isdir(q):
            if not a.trocken:
                if os.path.isdir(z):
                    shutil.rmtree(z)
                baum_kopieren(q, z, a.trocken)
        elif os.path.isfile(q):
            if not a.trocken:
                durchschreiben(q, z)
        else:
            fehlende.append(name)
    if fehlende and not a.trocken:
        if shutil.which("circup"):
            print("Hole ueber circup:", ", ".join(fehlende))
            r = subprocess.run(["circup", "--path", ziel, "install"] + fehlende)
            if r.returncode != 0:
                print("circup ist fehlgeschlagen - Bibliotheken bitte von Hand aus "
                      "https://circuitpython.org/libraries nach lib/ kopieren.")
        else:
            print("Fehlende Bibliotheken: %s\n  Entweder 'pip install circup' und das "
                  "Skript erneut starten,\n  oder aus https://circuitpython.org/libraries "
                  "(Bundle %s.x) nach lib/ kopieren." %
                  (", ".join(fehlende), (version or "10").split(".")[0]))

    # Firmware - boot.py als letzte Datei
    if not a.trocken:
        for i, (q, z) in enumerate(kopieren, 1):
            print("\r  kopiere %2d/%d  %-28s" % (i, len(kopieren), z), end="", flush=True)
            durchschreiben(q, os.path.join(ziel, z))
        print()
        sync()
        print("\nFertig. Jetzt das Laufwerk AUSWERFEN, dann abziehen und neu einstecken.")
        if belegung is None:
            print("Ohne device.json startet der Access Point 'UniversalGC-Setup' "
                  "(Passwort universalgc) von selbst: http://192.168.4.1")
        else:
            w = belegung.get("wifi", {}) if isinstance(belegung, dict) else {}
            print("Weboberflaeche: Konfigurationstaster kurz druecken, WLAN '%s', "
                  "http://192.168.4.1" % w.get("ssid", "?"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
