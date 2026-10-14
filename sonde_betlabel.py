"""14.10. (Lucio: "Ich brauche zu jedem meiner Märkte eine Quote, direkt im
Telegram"): Erkundung, wie BetLabel seine Quoten ausliefert. Läuft nur per
Push auf scan_now mit "BetLabel-Sonde" in der Commit-Nachricht und schreibt
runs/betlabel_sonde.json. Ändert am Scan nichts."""
import json, re, ssl, time, urllib.request, urllib.error, gzip, zlib
from pathlib import Path

UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36")

START = [
    "https://betlabel.com/",
    "https://betlabel.com/en/sports",
    "https://betlabel.com/de/sport",
    "https://betlbl.com/",
    "https://www.betlabel.com/",
]
# Bekannte Feed-Muster großer Plattformen — was antwortet, verrät die Technik.
PFADE = [
    "/LineFeed/Get1x2_VZip?sports=1&count=5&lng=de&mode=4&country=1&getEmpty=true",
    "/service-api/LineFeed/Get1x2_VZip?sports=1&count=5&lng=de&mode=4&country=1",
    "/api/v1/sports",
    "/api/sport/prematch",
    "/sportsbook",
    "/api/sportsbook/v1/events",
    "/robots.txt",
    "/sitemap.xml",
]
SUCH = re.compile(r"(wss?://[^\"'\s<>]+|https?://[a-z0-9.\-]*(?:api|feed|sport|odds|swarm|altenar|digitain|betconstruct|betby|sbtech|kambi|sportradar|bti|line)[a-z0-9.\-]*[^\"'\s<>]*)", re.I)
MARKEN = ("swarm", "betconstruct", "altenar", "digitain", "betby", "sbtech", "kambi",
          "bti", "LineFeed", "Get1x2", "sportradar", "oddin", "spinmatic", "sportsbook",
          "iframe", "__NEXT_DATA__", "nuxt", "graphql")


def hole(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "*/*", "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            raw = r.read(3_000_000)
            enc = r.headers.get("Content-Encoding", "")
            if enc == "gzip":
                raw = gzip.decompress(raw)
            elif enc == "deflate":
                raw = zlib.decompress(raw)
            return dict(url=url, final=r.geturl(), status=r.status,
                        headers=dict(r.headers), body=raw.decode("utf-8", "replace"),
                        ms=int((time.time() - t) * 1000))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(20000).decode("utf-8", "replace")
        except Exception:
            pass
        return dict(url=url, status=e.code, headers=dict(e.headers or {}), body=body)
    except Exception as e:
        return dict(url=url, status=None, error=f"{type(e).__name__}: {e}")


def kurz(r, n=1500):
    out = {k: v for k, v in r.items() if k != "body"}
    b = r.get("body") or ""
    out["len"] = len(b)
    out["anfang"] = b[:n]
    out["marken"] = sorted({m for m in MARKEN if m.lower() in b.lower()})
    out["urls"] = sorted(set(SUCH.findall(b)))[:80]
    return out


def run(_scan=None):
    erg = {"zeit": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "start": [], "pfade": [], "skripte": []}
    hosts = set()
    skripte = set()
    for u in START:
        r = hole(u)
        erg["start"].append(kurz(r, 4000))
        b = r.get("body") or ""
        if r.get("final"):
            m = re.match(r"(https?://[^/]+)", r["final"])
            if m:
                hosts.add(m.group(1))
        for s in re.findall(r"<(?:script|iframe)[^>]+src=[\"']([^\"']+)", b, re.I):
            if s.startswith("//"):
                s = "https:" + s
            elif s.startswith("/") and r.get("final"):
                s = re.match(r"(https?://[^/]+)", r["final"]).group(1) + s
            skripte.add(s)
        for s in re.findall(r"[\"'](/[^\"']+\.js)[\"']", b):
            if r.get("final"):
                skripte.add(re.match(r"(https?://[^/]+)", r["final"]).group(1) + s)
    for h in sorted(hosts) or ["https://betlabel.com"]:
        for p in PFADE:
            erg["pfade"].append(kurz(hole(h + p), 1200))
    for s in sorted(skripte)[:40]:
        r = hole(s)
        k = kurz(r, 300)
        erg["skripte"].append(k)
    Path("runs").mkdir(exist_ok=True)
    Path("runs/betlabel_sonde.json").write_text(json.dumps(erg, ensure_ascii=False, indent=1))
    print("BetLabel-Sonde fertig:", len(erg["start"]), "Startseiten,", len(erg["skripte"]), "Skripte")
