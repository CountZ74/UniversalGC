# SPDX-License-Identifier: GPL-3.0-or-later
# merker.py - kleine Merker im nichtfluechtigen Speicher (microcontroller.nvm)
#
# boot.py darf nicht auf das Dateisystem schreiben: waehrend es laeuft, hat
# CircuitPython boot_out.txt offen, und ein Umhaengen des Dateisystems endet
# in "OSError: [Errno 5]". Alles, was boot.py sich ueber einen Neustart hinweg
# merken muss, steht deshalb hier - ein paar Bytes im NVM-Bereich des Flash.
#
# Wartungsmodus von der Konsole aus (Thonny-Shell, vorher Strg+C):
#     import merker; merker.wartung()

WARTUNG = 0       # == W_MAGIC: naechster Start einmalig mit Laufwerk
FEHLSTARTS = 1    # Zahl der Starts mit unbestaetigter neuer Belegung
RUECKFALL = 2     # == R_MAGIC: alte Belegung zurueckholen (code.py kopiert)

W_MAGIC = 0x57
R_MAGIC = 0x52


def _nvm():
    try:
        import microcontroller
        n = microcontroller.nvm
        if n is not None and len(n) >= 4:
            return n
    except (ImportError, AttributeError):
        pass
    return None


def verfuegbar():
    return _nvm() is not None


def lesen(i):
    n = _nvm()
    if n is None:
        return 0
    v = n[i]
    return 0 if v == 0xFF else v       # geloeschter Flash steht auf 0xFF


def setzen(i, v):
    """Schreibt nur, wenn sich der Wert wirklich aendert - jeder Schreibvorgang
    loescht und beschreibt einen Flash-Sektor. Geloeschter Flash (0xFF) gilt
    als 0, wird also beim Setzen auf 0 nicht angefasst."""
    n = _nvm()
    if n is None:
        return False
    alt = n[i]
    if alt == v or (v == 0 and alt == 0xFF):
        return True
    n[i] = v
    return True


def wartung():
    """Neu starten, Laufwerk CIRCUITPY einmalig sichtbar."""
    if not setzen(WARTUNG, W_MAGIC):
        print("Kein NVM auf diesem Board - Konfigurationstaster benutzen")
        return
    import microcontroller
    microcontroller.reset()
