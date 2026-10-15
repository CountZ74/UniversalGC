# SPDX-License-Identifier: GPL-3.0-or-later
# code.py - UniversalGC
#
# Die Firmware selbst steckt in app.py (bzw. app.mpy im Release-Paket, in
# lib/). code.py bleibt bewusst klein: CircuitPython uebersetzt es bei jedem
# Start aus dem Quelltext, und das kostet auf dem Pico W wertvollen Speicher.
# Beschreibung, Bedienung und Dateiliste: siehe app.py und README.md.

import app

app.start()
