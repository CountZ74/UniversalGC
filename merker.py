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


# --- Entwurf: eine Belegung, die gespeichert werden soll ---------------------
#
# Ist das Laufwerk CIRCUITPY fuer den PC freigegeben (Einrichtung, Wartung,
# oder nach dem Kopieren noch kein echter Neustart), kann das Geraet keine
# Datei schreiben. Die neue Belegung wandert dann hierher, das Geraet startet
# neu, boot.py meldet sich schon mit ihr an und sperrt das Laufwerk, und
# code.py schreibt sie als device.json.
#
# Ab Byte 16:  "UGCJ" + Laenge (2 Byte) + JSON (UTF-8)

E_START = 16
E_MAGIC = b"UGCJ"


def entwurf_platz():
    n = _nvm()
    return 0 if n is None else len(n) - E_START - 6


def entwurf_schreiben(text):
    n = _nvm()
    d = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    if n is None or len(d) > entwurf_platz():
        return False
    k = len(d)
    # Ein Slice = ein Schreibvorgang auf den Flash
    n[E_START:E_START + 6 + k] = E_MAGIC + bytes((k >> 8, k & 255)) + d
    return True


def entwurf_lesen():
    n = _nvm()
    if n is None or len(n) < E_START + 6:
        return None
    if bytes(n[E_START:E_START + 4]) != E_MAGIC:
        return None
    k = (n[E_START + 4] << 8) | n[E_START + 5]
    if k > entwurf_platz():
        return None
    try:
        return bytes(n[E_START + 6:E_START + 6 + k]).decode("utf-8")
    except UnicodeError:
        return None


def entwurf_loeschen():
    n = _nvm()
    if n is not None and len(n) > E_START and n[E_START] != 0:
        n[E_START] = 0
