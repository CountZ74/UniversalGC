# SPDX-License-Identifier: GPL-3.0-or-later
# web.py - Access Point und Weboberflaeche
#
# Alle Sockets laufen nicht blockierend. Waehrend auf einen Browser gewartet
# wird, laeuft die Hauptschleife ueber app.schritt() weiter - Buttons, Achsen,
# Rumble-Totmannschaltung und Sweep-Messung stehen nie still (Buttonbox v2,
# Pedale v9.2). Die Oberflaeche liegt als statische index.html im Flash und
# wird gechunkt gesendet; danach gehen nur kleine JSON-Antworten hin und her.

import json
import os
import time
import gc

INDEX_FILE = "/index.html"
ZEICHEN = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


class Web:
    def __init__(self, app):
        self.app = app
        self.aktiv = False
        self.sock = None
        self.pool = None
        self.stoppen = False

    # --- Access Point ---

    def starten(self):
        import wifi
        import socketpool
        w = self.app.c["wifi"]
        pw = w.get("password") or None
        print("Starte AP", w.get("ssid"), "...")
        wifi.radio.start_ap(ssid=w.get("ssid", "UniversalGC"), password=pw,
                            channel=int(w.get("channel", 6)))
        self.pool = socketpool.SocketPool(wifi.radio)
        self.sock = self.pool.socket(self.pool.AF_INET, self.pool.SOCK_STREAM)
        self.sock.setsockopt(self.pool.SOL_SOCKET, self.pool.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", int(w.get("port", 80))))
        self.sock.listen(4)              # Browser oeffnen mehrere Verbindungen
        self.sock.setblocking(False)
        self.aktiv = True
        print("Webserver: http://192.168.4.1")

    def beenden(self):
        try:
            if self.sock:
                self.sock.close()
            import wifi
            wifi.radio.stop_ap()
        except Exception as e:
            print("AP-Stopp:", e)
        self.sock = None
        self.aktiv = False
        self.stoppen = False

    def bedienen(self):
        """Hoechstens eine Verbindung annehmen und abarbeiten."""
        conn = None
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        conn.setblocking(False)
        try:
            self.handle(conn)
        except Exception as e:
            print("Request-Fehler:", e)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        gc.collect()

    # --- HTTP-Grundlagen ---

    def _send_all(self, conn, data):
        mv = memoryview(data)
        ende = time.monotonic() + 5.0
        while len(mv):
            try:
                n = conn.send(mv)
            except OSError:
                n = 0                    # Sendepuffer voll, gleich nochmal
            if n:
                mv = mv[n:]
                continue
            if time.monotonic() > ende:
                break                    # Gegenstelle weg
            self.app.schritt(time.monotonic())

    def send(self, conn, status, ctype, body, cache=None):
        if isinstance(body, str):
            body = body.encode()
        h = ["HTTP/1.1 " + status, "Content-Type: " + ctype,
             "Content-Length: " + str(len(body)), "Connection: close"]
        if cache:
            h.append("Cache-Control: " + cache)
        self._send_all(conn, ("\r\n".join(h) + "\r\n\r\n").encode())
        self._send_all(conn, body)

    def json(self, conn, obj):
        self.send(conn, "200 OK", "application/json", json.dumps(obj), "no-store")

    def datei(self, conn, pfad, ctype, cache="max-age=3600"):
        try:
            groesse = os.stat(pfad)[6]
        except OSError:
            self.send(conn, "404 Not Found", "text/plain", pfad + " fehlt")
            return
        kopf = ("HTTP/1.1 200 OK\r\nContent-Type: " + ctype +
                "\r\nContent-Length: " + str(groesse) +
                "\r\nCache-Control: " + cache + "\r\nConnection: close\r\n\r\n")
        self._send_all(conn, kopf.encode())
        buf = bytearray(1024)
        with open(pfad, "rb") as f:
            while True:
                n = f.readinto(buf)
                if not n:
                    break
                self._send_all(conn, memoryview(buf)[:n])

    def _recv_warten(self, conn, buf, frist):
        """Browser oeffnen Verbindungen auf Vorrat und schicken spaeter oder
        nie etwas. Gewartet wird deshalb pollend, die Schleife laeuft weiter."""
        ende = time.monotonic() + frist
        while time.monotonic() < ende:
            try:
                n = conn.recv_into(buf)
                if n:
                    return n
            except OSError:
                pass
            self.app.schritt(time.monotonic())
        return 0

    def lesen(self, conn):
        buf = bytearray(1024)
        n = self._recv_warten(conn, buf, 1.0)
        if not n:
            return "", "", ""
        roh = bytes(buf[:n])
        trenn = roh.find(b"\r\n\r\n")
        if trenn < 0:
            kopf, body = roh.decode("utf-8", "ignore"), b""
        else:
            kopf = roh[:trenn].decode("utf-8", "ignore")
            body = roh[trenn + 4:]
        laenge = 0
        for zeile in kopf.split("\r\n"):
            if zeile[:15].lower() == "content-length:":
                try:
                    laenge = int(zeile.split(":", 1)[1])
                except ValueError:
                    laenge = 0
                break
        if laenge > 16384:
            laenge = 16384
        teile = [body]
        da = len(body)
        while da < laenge:               # Body passt oft nicht ins erste Paket
            n = self._recv_warten(conn, buf, 0.5)
            if not n:
                break
            teile.append(bytes(buf[:n]))
            da += n
        try:
            pfad = kopf.split("\r\n")[0].split(" ")[1]
        except IndexError:
            pfad = "/"
        return kopf, pfad, b"".join(teile).decode("utf-8", "ignore")

    @staticmethod
    def param(pfad, key):
        if "?" not in pfad:
            return None
        for p in pfad.split("?", 1)[1].split("&"):
            if "=" in p:
                k, v = p.split("=", 1)
                if k == key:
                    return v
        return None

    def _int(self, pfad, key):
        v = self.param(pfad, key)
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    # --- Routen ---

    def handle(self, conn):
        kopf, pfad, body = self.lesen(conn)
        if not kopf:
            return
        app = self.app
        p = pfad.split("?", 1)[0]

        if p in ("/", "/index.html"):
            self.datei(conn, INDEX_FILE, "text/html; charset=utf-8")
        elif p == "/init":
            self.json(conn, app.init_json())
        elif p == "/data":
            self.json(conn, app.data_json())

        # Kalibrierung
        elif p == "/cal_start":
            app.cal_start(self._int(pfad, "a"))
            self.json(conn, app.data_json())
        elif p == "/cal_zero":
            app.cal_zero()
            self.json(conn, app.data_json())
        elif p == "/cal_finish":
            app.cal_finish()
            self.json(conn, app.data_json())
        elif p == "/cal_abort":
            app.cal_abort()
            self.json(conn, app.data_json())
        elif p == "/cal_reset":
            app.cal_reset(self._int(pfad, "a"))
            self.json(conn, app.data_json())
        elif p == "/cal_flip":
            app.cal_flip(self._int(pfad, "a"))
            self.json(conn, app.data_json())
        elif p == "/tare":
            app.tarieren(self._int(pfad, "a"))
            self.json(conn, app.data_json())
        elif p == "/kurve":
            try:
                d = json.loads(body)
                self.json(conn, {"ok": app.kurve_setzen(int(d["achse"]), d["curve"])})
            except (ValueError, KeyError, TypeError):
                self.json(conn, {"ok": False})

        # Logik, LEDs
        elif p == "/logik":
            try:
                ok, fehler = app.logik_setzen(json.loads(body))
            except (ValueError, TypeError) as e:
                ok, fehler = False, [str(e)]
            self.json(conn, {"ok": ok, "f": fehler, "lg": app.lg})

        # Rumble
        elif p == "/rumble_set":
            ok = False
            if app.rumble:
                try:
                    ok = app.rumble.setzen(json.loads(body))
                except (ValueError, TypeError) as e:
                    print("Rumble-Einstellungen fehlerhaft:", e)
            self.json(conn, {"ok": ok, "rc": app.rumble.cfg if app.rumble else []})
        elif p == "/rumble_test":
            if app.rumble:
                try:
                    s = self.param(pfad, "s")
                    app.rumble.test_setzen(int(self.param(pfad, "k")),
                                           float(self.param(pfad, "v")),
                                           int(s) if s is not None else None)
                except (TypeError, ValueError):
                    pass
            self.json(conn, {"ok": True})
        elif p == "/rumble_stop":
            if app.rumble:
                app.rumble.not_aus()
            self.json(conn, {"ok": True})

        # Geraetekonfiguration
        elif p == "/config":
            if kopf.startswith("POST"):
                self.json(conn, app.config_speichern(body))
            else:
                self.send(conn, "200 OK", "application/json",
                          json.dumps(app.c), "no-store")
        elif p == "/pruefen":
            self.json(conn, app.config_pruefen(body))
        elif p == "/preset":
            name = self.param(pfad, "n") or ""
            if name and all(ch in ZEICHEN for ch in name):
                self.datei(conn, "/presets/" + name + ".json",
                           "application/json", "no-store")
            else:
                self.send(conn, "404 Not Found", "text/plain", "404")
        elif p == "/neustart":
            self.json(conn, {"ok": True})
            app.neustart_bei = time.monotonic() + 0.8

        elif p == "/wlan_aus":
            self.json(conn, {"ok": True})
            self.stoppen = True
        elif p == "/favicon.ico":
            self._send_all(conn, b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n"
                                 b"Connection: close\r\n\r\n")
        else:
            self.send(conn, "404 Not Found", "text/plain", "404")
