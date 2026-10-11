# logik.py - Logikausdruecke aus der Buttonbox, fuer alle Geraete
#
# Funktionen  AND(x,y,...)  OR(x,y,...)  NOT(x)
#             GT(a,b)  LT(a,b)  GE(a,b)  LE(a,b)  EQ(a,b)
# Buttons     b0, b1, ...   Button 1, 2, ... (physischer Zustand, vor dem
#                           Unterdruecken; s0.. bedeutet dasselbe)
# Achsen      a0, a1, ...   Achse 1, 2, ... in Prozent (0..100)
# Telemetrie  jeder Name, den SimHub schickt, z.B. motor oder rpm
# Zahlen      als Literal, z.B. GT(rpm,7000)
#
# Beispiele
#   AND(b9,b10)              Zuendung 1 und 2 an
#   AND(b9,b10,NOT(motor))   Zuendung an, Motor laeuft noch nicht
#   GT(a0,90)                Gaspedal ueber 90 Prozent
#
# Keine Hardware-Importe - die Tests laufen auf dem PC.


def _args_teilen(s):
    """Komma-getrennte Argumente aufteilen, Klammern respektieren."""
    args, tiefe, akt = [], 0, ""
    for ch in s:
        if ch == "(":
            tiefe += 1
            akt += ch
        elif ch == ")":
            tiefe -= 1
            akt += ch
        elif ch == "," and tiefe == 0:
            args.append(akt.strip())
            akt = ""
        else:
            akt += ch
    if akt.strip():
        args.append(akt.strip())
    return args


def _zahl(token, ctx):
    """Einen Namen oder eine Zahl zu einem Zahlenwert aufloesen.

    ctx ist ein Objekt mit
      button(i) -> bool     physischer Zustand von Button i (0-basiert)
      achse(i)  -> float    Achse i in Prozent
      tele      dict        Telemetriewerte, Namen kleingeschrieben
    """
    t = token.strip()
    if not t:
        return 0.0
    k = t[0].lower()
    if k in "bs" and t[1:].isdigit():
        return 1.0 if ctx.button(int(t[1:])) else 0.0
    if k == "a" and t[1:].isdigit():
        return float(ctx.achse(int(t[1:])))
    try:
        return float(t)
    except ValueError:
        pass
    v = ctx.tele.get(t.lower())
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    # Manche Quellen schicken "True"/"False" statt 1/0. Ohne diese Zeilen waere
    # auch "False" ein nicht leerer Text und damit wahr.
    s = str(v).strip().lower()
    if s in ("true", "yes", "on"):
        return 1.0
    if s in ("false", "no", "off", ""):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 1.0


_VERGLEICH = {
    "GT": lambda a, b: a > b,
    "LT": lambda a, b: a < b,
    "GE": lambda a, b: a >= b,
    "LE": lambda a, b: a <= b,
    "EQ": lambda a, b: a == b,
}


def werten(expr, ctx):
    """Wertet einen Logikausdruck aus. Fehler ergeben immer False."""
    if not expr:
        return False

    def rechne(e, tiefe):
        e = e.strip()
        if not e or tiefe > 12:          # Schutz vor endloser Verschachtelung
            return False
        gross = e.upper()
        if gross.startswith("AND(") and e.endswith(")"):
            return all(rechne(p, tiefe + 1) for p in _args_teilen(e[4:-1]))
        if gross.startswith("OR(") and e.endswith(")"):
            return any(rechne(p, tiefe + 1) for p in _args_teilen(e[3:-1]))
        if gross.startswith("NOT(") and e.endswith(")"):
            return not rechne(e[4:-1], tiefe + 1)
        for name, op in _VERGLEICH.items():
            if gross.startswith(name + "(") and e.endswith(")"):
                teile = _args_teilen(e[len(name) + 1:-1])
                if len(teile) != 2:
                    return False
                return op(_zahl(teile[0], ctx), _zahl(teile[1], ctx))
        return _zahl(e, ctx) != 0.0

    try:
        return bool(rechne(expr, 0))
    except (ValueError, TypeError, IndexError, KeyError):
        return False
