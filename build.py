"""Kijkgids: haalt dagelijks de gratis tv-gids op en maakt er kleine bestanden per dag van.

Gebruik:  python build.py            (downloadt van iptv-epg.org)
          python build.py bestand.gz (gebruikt een lokaal bestand, om te testen)
"""
import gzip, hashlib, json, os, re, sys, unicodedata, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BRON = "https://iptv-epg.org/files/epg-nl.xml.gz"
NL = ZoneInfo("Europe/Amsterdam")
SITE = "site"              # wat online komt (GitHub Pages)
ARCHIEF = "data/archief"   # afgelopen dagen, voor 'Mogelijk gemist'
DAGEN_TERUG = 7

# Zendernaam in de bron  ->  naam in de app
ZENDERS = {
    "NL - NPO 1": "NPO 1", "NL - NPO 2": "NPO 2", "NL - NPO 3": "NPO 3",
    "NL - RTL 4": "RTL 4", "NL - RTL 5": "RTL 5", "NL - RTL 7": "RTL 7", "NL - RTL 8": "RTL 8",
    "NL - SBS6": "SBS6", "NL - Net5": "Net5", "NL - Veronica / Disney XD": "Veronica", "NL - SBS9": "SBS9",
    "NL - ESPN": "ESPN", "NL - ESPN 2": "ESPN 2", "NL - ESPN 3": "ESPN 3", "NL - ESPN 4": "ESPN 4",
    "NL - Ziggo Sport": "Ziggo Sport", "NL - Ziggo Sport 2": "Ziggo Sport 2",
    "NL - Eurosport 1": "Eurosport 1", "NL - Viaplay TV": "Viaplay TV",
    "NL - BBC One": "BBC One", "NL - BBC Two": "BBC Two",
    "NL - ARD": "ARD", "NL - ZDF": "ZDF", "NL - Arte": "Arte",
    "NL - één": "één", "NL - Canvas": "Canvas",
    "NL - Discovery": "Discovery", "NL - National Geographic Channel": "National Geographic",
    "NL - Comedy Central": "Comedy Central", "NL - TLC": "TLC",
}


def tijd(s):
    """XMLTV-tijd '20261006183000 +0000' -> Nederlandse tijd."""
    t = datetime.strptime(s[:14], "%Y%m%d%H%M%S")
    off = s[15:].strip() or "+0000"
    tz = timezone(timedelta(hours=int(off[:3]), minutes=int(off[0] + off[3:5])))
    return t.replace(tzinfo=tz).astimezone(NL)


def lees(bron):
    if os.path.exists(bron):
        data = open(bron, "rb").read()
    else:
        req = urllib.request.Request(bron, headers={"User-Agent": "Kijkgids (familie, 1x per dag)"})
        data = urllib.request.urlopen(req, timeout=120).read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def verwerk(xml):
    namen, uit = {}, []
    root = ET.fromstring(xml)
    for c in root.iter("channel"):
        namen[c.get("id")] = c.findtext("display-name")
    for p in root.iter("programme"):
        zender = ZENDERS.get(namen.get(p.get("channel")))
        if not zender:
            continue
        start, eind = tijd(p.get("start")), tijd(p.get("stop"))
        desc = (p.findtext("desc") or "").strip()
        cats = [c.text for c in p.findall("category") if c.text]
        regel1, _, rest = desc.partition("\n")
        # Bij wedstrijden staan de ploegen op de eerste regel ("Feyenoord - AZ")
        sub = regel1.strip() if (" - " in regel1 and len(regel1) < 80) else ""
        ep = p.findtext("episode-num")
        icon = p.find("icon")
        img = icon.get("src") if icon is not None else ""
        prime = 18 <= start.hour or start.hour < 1
        uit.append({
            "z": zender,
            "s": start.isoformat(timespec="minutes"),
            "e": eind.isoformat(timespec="minutes"),
            "t": (p.findtext("title") or "").strip(),
            **({"sub": sub} if sub else {}),
            "d": (rest if sub else desc).strip()[:220],
            "c": cats[:3],
            **({"ep": ep.strip()} if ep else {}),
            **({"jr": p.findtext("date")} if p.findtext("date") else {}),
            **({"img": img} if img and (prime or "Film" in cats) else {}),
            **({"live": 1} if p.find("live") is not None else {}),
        })
    return uit


# ---------- Voetbalagenda (abonneer in Google Agenda) ----------
def norm(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").replace("&", " en ")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def wedstrijd(p):
    """Geeft 'wk', 'ek', 'eredivisie', 'nations' of None — zelfde regels als de app."""
    t, s = norm(p["t"]), norm(p.get("sub", ""))
    alles = t + " " + s
    if not ("Voetbal" in p["c"] or re.search(r"soccer|fifa|voetbal|uefa", t)):
        return None
    if re.search(r"samenvatting|highlights|hoogtepunten|goedemorgen|voorbeschouwing|nabeschouwing|switch", alles) or p.get("d", "").lower().startswith("samenvatting"):
        return None
    if re.search(r"(^| )(u ?21|o21|onder 21)( |$)", alles):
        return None
    if re.search(r"world cup|wereldkampioenschap|(^| )wk( |$)", t): return "wk"
    if re.search(r"euro(pean)? championship|europees kampioenschap|(^| )ek( |$)|euro 20\d\d", t): return "ek"
    if "eredivisie" in t and not re.search(r"vrouwen|women", t): return "eredivisie"
    if "nations league" in t: return "nations"
    return None


def ics_tekst(t):
    return t.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def maak_agenda(naam, programmas, pad):
    nu = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    regels = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Kijkgids//Voetbal//NL", "CALSCALE:GREGORIAN",
              "METHOD:PUBLISH", "X-WR-CALNAME:" + naam, "X-WR-TIMEZONE:Europe/Amsterdam",
              "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for p in programmas:
        start = datetime.fromisoformat(p["s"]).astimezone(timezone.utc)
        eind = datetime.fromisoformat(p["e"]).astimezone(timezone.utc)
        titel = (p.get("sub") or p["t"]) + " · " + p["z"]
        uid = hashlib.sha1((norm(p["t"]) + norm(p.get("sub", "")) + p["s"]).encode()).hexdigest()
        regels += ["BEGIN:VEVENT", "UID:" + uid + "@kijkgids", "DTSTAMP:" + nu,
                   "DTSTART:" + start.strftime("%Y%m%dT%H%M%SZ"), "DTEND:" + eind.strftime("%Y%m%dT%H%M%SZ"),
                   "SUMMARY:" + ics_tekst(titel), "LOCATION:" + ics_tekst(p["z"]),
                   "DESCRIPTION:" + ics_tekst(p["t"] + (" — " + p["d"] if p.get("d") else "")),
                   "BEGIN:VALARM", "TRIGGER:-PT15M", "ACTION:DISPLAY", "DESCRIPTION:" + ics_tekst(titel), "END:VALARM",
                   "END:VEVENT"]
    regels.append("END:VCALENDAR")
    # ICS-regels mogen maximaal 75 bytes zijn; langere regels worden gevouwen
    uit = []
    for r in regels:
        b = r.encode()
        while len(b) > 75:
            knip = 75
            while (b[knip] & 0xC0) == 0x80:
                knip -= 1
            uit.append(b[:knip].decode()); b = b" " + b[knip:]
        uit.append(b.decode())
    open(pad, "w", newline="").write("\r\n".join(uit) + "\r\n")


def voetbalagenda(per_dag):
    eerste = {}
    for lijst in per_dag.values():
        for p in lijst:
            soort = wedstrijd(p)
            if not soort:
                continue
            p["_soort"] = soort
            k = norm(p.get("sub") or p["t"])          # zelfde wedstrijd = herhaling
            if k not in eerste or p["s"] < eerste[k]["s"]:
                eerste[k] = p
    # Is de eerste uitzending 's nachts of 's ochtends (01–10 uur), dan is het een herhaling van een eerder gespeelde wedstrijd
    alles = sorted((p for p in eerste.values() if not 1 <= int(p["s"][11:13]) < 10), key=lambda p: p["s"])
    oranje = lambda p: re.search(r"(^| )nederland( |$)", norm(p.get("sub", "")))
    maak_agenda("Kijkgids · Voetbal", [p for p in alles if p["_soort"] in ("wk", "ek", "eredivisie")], f"{SITE}/voetbal.ics")
    maak_agenda("Kijkgids · Feyenoord & Oranje",
                [p for p in alles if "feyenoord" in norm(p.get("sub", "") + " " + p.get("d", "")) or (p["_soort"] in ("wk", "ek", "nations") and oranje(p))],
                f"{SITE}/feyenoord-oranje.ics")
    for p in alles:
        p.pop("_soort", None)


def main():
    bron = sys.argv[1] if len(sys.argv) > 1 else BRON
    nieuw = verwerk(lees(bron))
    if not nieuw:
        sys.exit("Geen programma's gevonden: bron veranderd of leeg. Oude bestanden blijven staan.")

    per_dag = {}
    for p in nieuw:
        per_dag.setdefault(p["s"][:10], []).append(p)

    vandaag = datetime.now(NL).date()
    os.makedirs(ARCHIEF, exist_ok=True)
    # Afgelopen dagen bewaren: de bron begint elke dag opnieuw bij vandaag
    for dag, lijst in per_dag.items():
        if datetime.fromisoformat(dag).date() <= vandaag:
            json.dump(lijst, open(f"{ARCHIEF}/{dag}.json", "w"), ensure_ascii=False, separators=(",", ":"))
    for f in os.listdir(ARCHIEF):
        dag = datetime.fromisoformat(f[:10]).date()
        if dag < vandaag - timedelta(days=DAGEN_TERUG):
            os.remove(f"{ARCHIEF}/{f}")
        elif dag < vandaag and f[:10] not in per_dag:
            per_dag[f[:10]] = json.load(open(f"{ARCHIEF}/{f}"))

    os.makedirs(SITE, exist_ok=True)
    for f in os.listdir(SITE):
        os.remove(f"{SITE}/{f}")
    voetbalagenda(per_dag)
    dagen = sorted(per_dag)
    for dag in dagen:
        lijst = sorted(per_dag[dag], key=lambda p: (p["s"], p["z"]))
        json.dump(lijst, open(f"{SITE}/{dag}.json", "w"), ensure_ascii=False, separators=(",", ":"))
    json.dump({
        "bijgewerkt": datetime.now(NL).isoformat(timespec="minutes"),
        "dagen": dagen,
        "zenders": list(dict.fromkeys(ZENDERS.values())),
        "bron": "IPTV-EPG.org",
    }, open(f"{SITE}/index.json", "w"), ensure_ascii=False, indent=1)
    print(f"{len(nieuw)} programma's, dagen {dagen[0]} t/m {dagen[-1]}")


if __name__ == "__main__":
    main()
