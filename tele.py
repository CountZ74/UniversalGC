# SPDX-License-Identifier: GPL-3.0-or-later
# tele.py - Telemetrie von SimHub ueber den zweiten seriellen Kanal
#
# Format wie bisher bei Pedalen und Buttonbox, eine Zeile je Aktualisierung:
#     motor=1;rpm=1450;gang=3;bremse=40
# Namen werden kleingeschrieben abgelegt. Werte werden als Zahl gelesen, wenn
# das geht, sonst bleibt der Text stehen (fuer die Logik: "True" usw.).
#
# Die Klasse bekommt den Port von aussen - auf dem PC laesst sie sich so mit
# einem Nachbau testen.


class Telemetrie:
    def __init__(self, port, timeout=2.0):
        self.port = port
        self.timeout = timeout
        self.werte = {}
        self.zeit = 0.0
        self.zeilen = 0
        self.bytes = 0
        self.roh = ""
        self._puffer = ""
        self._letzte = 0.0

    def _zeile(self, zeile, now):
        zeile = zeile.strip()
        if not zeile:
            return
        neu = {}
        for teil in zeile.replace(",", ";").split(";"):
            if "=" not in teil:
                continue
            name, _, wert = teil.partition("=")
            name = name.strip().lower()
            if not name:
                continue
            wert = wert.strip()
            try:
                neu[name] = float(wert)
            except ValueError:
                neu[name] = wert
        if neu:
            self.werte.update(neu)
            self.zeit = now
            self.zeilen += 1

    def lesen(self, now):
        """Nicht blockierend. Muss in jeder Runde laufen.

        Rueckgabe: True, wenn die Werte gerade wegen Zeitueberschreitung
        verworfen wurden (dann muessen Motoren und LEDs aus).
        """
        if self.port is not None:
            try:
                n = self.port.in_waiting
                if n:
                    roh = self.port.read(n)
                    if roh:
                        text = roh.decode("utf-8", "ignore")
                        self.bytes += len(text)
                        self._letzte = now
                        self.roh = (self.roh + text)[-80:]
                        self._puffer += text.replace("\r", "\n")
                        while "\n" in self._puffer:
                            z, self._puffer = self._puffer.split("\n", 1)
                            self._zeile(z, now)
                        if len(self._puffer) > 512:    # Muell, nie ein Zeilenende
                            self._puffer = self._puffer[-200:]
            except Exception:
                pass

        # Rettungsanker: Daten da, aber kein Zeilenumbruch. Passiert, wenn in
        # SimHub das \n in der Formel fehlt - der haeufigste Anfaengerfehler.
        if self._puffer and (now - self._letzte) > 0.5:
            self._zeile(self._puffer, now)
            self._puffer = ""

        if self.werte and (now - self.zeit) > self.timeout:
            # SimHub weg oder Spiel beendet: nichts im letzten Zustand
            # haengen lassen.
            self.werte.clear()
            return True
        return False

    def zustand(self):
        """0 = nichts empfangen, 1 = Daten ohne Zeile, 2 = verbunden."""
        if self.bytes == 0:
            return 0
        if self.zeilen == 0:
            return 1
        return 2

    def json(self):
        return {"tz": self.zustand(), "tb": self.bytes, "tl": self.zeilen,
                "tr": self.roh[-40:], "tv": self.werte}
