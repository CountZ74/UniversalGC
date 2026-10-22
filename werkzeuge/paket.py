#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Release-Paket bauen: Module vorkompiliert (.mpy), fertig fuer CIRCUITPY.

    python3 werkzeuge/paket.py --mpy-cross PFAD [--bundle BUNDLE.zip] [--ausgabe dist]

--mpy-cross  mpy-cross von CircuitPython (nicht von MicroPython!), passend zur
             Hauptversion auf dem Board. Bauen: im CircuitPython-Quelltext
             "make -C mpy-cross" (siehe .github/workflows/paket.yml).
--bundle     Adafruit-Bibliotheks-Bundle (*-mpy-*.zip) derselben Hauptversion.
             Daraus kommen neopixel, adafruit_ble, adafruit_pioasm und
             adafruit_hx711 ins Paket. Ohne --bundle holt installieren.py sie
             spaeter ueber circup.

Ergebnis: dist/UniversalGC-<version>-cp<N>.zip mit
    boot.py code.py index.html installieren.py VERSION LIESMICH.txt LICENSE
    presets/*.json
    lib/app.mpy lib/cfg.mpy ...           die Firmware
    lib/neopixel.mpy lib/adafruit_ble/ ... die Bibliotheken (mit --bundle)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from installieren import MODULE, BIBLIOTHEKEN, bundle_eintraege   # noqa: E402

LIESMICH = """UniversalGC {v} fuer CircuitPython {cp}.x
==========================================

Installieren / aktualisieren (Laufwerk CIRCUITPY muss sichtbar sein):

    python3 installieren.py            aktualisieren, Belegung bleibt
    python3 installieren.py lenkrad    mit Vorlage als device.json

Ohne Python: den gesamten Inhalt dieses Ordners auf CIRCUITPY kopieren,
boot.py als letzte Datei, danach das Laufwerk auswerfen. Alte .py-Dateien
der Firmware im Hauptverzeichnis vorher loeschen - sie verdecken die neuen
.mpy-Dateien in lib/.

Dieses Paket passt nur zu CircuitPython {cp}.x.
Beschreibung: https://github.com/CountZ74/UniversalGC
Die Bibliotheken in lib/ (neopixel, adafruit_*) stammen von Adafruit und
stehen unter der MIT-Lizenz. UniversalGC selbst: GPL-3.0-or-later (LICENSE).
"""


def version():
    with open(os.path.join(REPO, "app.py"), encoding="utf-8") as f:
        m = re.search(r'^VERSION = "([^"]+)"', f.read(), re.M)
    return m.group(1) if m else "0"


def cp_hauptversion(mpy_cross):
    out = subprocess.run([mpy_cross, "--version"], capture_output=True,
                         text=True).stdout
    m = re.search(r"CircuitPython (\d+)\.", out)
    if not m:
        raise SystemExit("%s ist kein mpy-cross von CircuitPython:\n%s" %
                         (mpy_cross, out))
    return m.group(1), out.strip()


def bibliotheken_aus_bundle(bundle, ziel_lib):
    with zipfile.ZipFile(bundle) as z:
        for lib in BIBLIOTHEKEN:
            dateien = bundle_eintraege(z, lib)
            if not dateien:
                print("  WARNUNG: %s nicht im Bundle" % lib)
                continue
            for rel, daten in dateien:
                ziel = os.path.join(ziel_lib, rel)
                os.makedirs(os.path.dirname(ziel), exist_ok=True)
                with open(ziel, "wb") as f:
                    f.write(daten)
            print("  Bibliothek", lib)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mpy-cross", required=True)
    ap.add_argument("--bundle")
    ap.add_argument("--ausgabe", default=os.path.join(REPO, "dist"))
    a = ap.parse_args()

    cp, kennung = cp_hauptversion(a.mpy_cross)
    v = version()
    name = "UniversalGC-%s-cp%s" % (v, cp)
    ordner = os.path.join(a.ausgabe, name)
    if os.path.exists(ordner):
        shutil.rmtree(ordner)
    lib = os.path.join(ordner, "lib")
    os.makedirs(lib)
    print("Baue", name, "mit", kennung)

    for m in MODULE:
        r = subprocess.run([a.mpy_cross, "-o", os.path.join(lib, m + ".mpy"),
                            os.path.join(REPO, m + ".py")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("mpy-cross %s.py:\n%s%s" % (m, r.stdout, r.stderr))
    print("  %d Module kompiliert" % len(MODULE))

    for n in ("boot.py", "code.py", "index.html", "installieren.py",
              "uebernahme.py", "LICENSE"):
        shutil.copy(os.path.join(REPO, n), ordner)
    shutil.copytree(os.path.join(REPO, "presets"), os.path.join(ordner, "presets"))
    with open(os.path.join(ordner, "VERSION"), "w", encoding="utf-8") as f:
        json.dump({"universalgc": v, "circuitpython": cp, "mpy_cross": kennung}, f)
    with open(os.path.join(ordner, "LIESMICH.txt"), "w", encoding="utf-8") as f:
        f.write(LIESMICH.format(v=v, cp=cp))

    if a.bundle:
        bibliotheken_aus_bundle(a.bundle, lib)

    zipname = os.path.join(a.ausgabe, name + ".zip")
    with zipfile.ZipFile(zipname, "w", zipfile.ZIP_DEFLATED) as z:
        for wurzel, _, dateien in os.walk(ordner):
            for n in sorted(dateien):
                p = os.path.join(wurzel, n)
                z.write(p, os.path.relpath(p, a.ausgabe))
    print("Fertig:", zipname, "(%d kB)" % (os.path.getsize(zipname) // 1024))
    return zipname


if __name__ == "__main__":
    main()
