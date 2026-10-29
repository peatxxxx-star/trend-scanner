"""29.10. (Lucio: „das mit diesen Codes müsstest du prüfen“): Kann man bei BetLabel (1xBet-Plattform)
einen Wettschein per Code/Link vorbefüllen? Nur Lesen/Anlegen eines Coupon-Codes, KEINE Wette.
Ergebnis: runs/coupon_test_<Zeit>.json (Statuscodes, gekürzte Antworten, Fundstellen im Seiten-JS)."""
import json, re, time, urllib.request, urllib.error, gzip, zlib
from pathlib import Path
import betlabel

HOSTS = ["https://betlabel.com", "https://betlbl.com"]


def _req(url, data=None, ctype="application/json", timeout=20):
    h = {"User-Agent": betlabel.UA, "Accept": "application/json, text/plain, */*", "Accept-Encoding": "gzip, deflate"}
    if data is not None:
        h["Content-Type"] = ctype
    r = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as x:
            raw = x.read(); enc = x.headers.get("Content-Encoding", "")
            raw = gzip.decompress(raw) if enc == "gzip" else zlib.decompress(raw) if enc == "deflate" else raw
            return x.status, raw.decode("utf-8", "replace"), x.geturl()
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"")[:400].decode("utf-8", "replace"), url
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", url


def run(runs_dir):
    out = {"zeit": time.strftime("%Y-%m-%d %H:%M"), "probes": [], "js": {}}
    # ein echtes Ereignis (1X2 Heimsieg) aus einem laufenden Fußballspiel
    ev = None
    try:
        spiele = betlabel.lade_spiele()
        g = next(x for x in spiele if x.get("I"))
        d = betlabel._spiel_detail(g["I"])
        e0 = (d.get("E") or [{}])[0]
        ev = {"GameId": d.get("I"), "Type": e0.get("T"), "Coef": e0.get("C"), "Param": e0.get("P", 0),
              "PlayerId": 0, "Kind": 3, "Expired": 0, "Price": 0, "InstrumentId": 0, "Seconds": 0}
        out["ereignis"] = {"spiel": f"{g.get('O1')} – {g.get('O2')}", **ev}
    except Exception as e:
        out["ereignis_fehler"] = f"{type(e).__name__}: {e}"
    pfade_post = ["/LiveUtil/SaveCoupon", "/service-api/LiveUtil/SaveCoupon", "/datalinelive/SaveCoupon",
                  "/web-api/LiveUtil/SaveCoupon", "/LiveUtil/SaveBetslip"]
    pfade_get = ["/LiveUtil/GetCoupon?code=TEST123", "/service-api/LiveUtil/GetCoupon?code=TEST123",
                 "/LiveUtil/GetCoupon?id=TEST123"]
    body = json.dumps({"Coupon": {"Events": [ev] if ev else [], "Lng": "de", "Vid": 0, "partner": 0}}).encode()
    for h in HOSTS:
        for p in pfade_post:
            st, txt, u = _req(h + p, data=body)
            out["probes"].append({"url": h + p, "methode": "POST", "status": st, "antwort": (txt or "")[:300]})
        for p in pfade_get:
            st, txt, u = _req(h + p)
            out["probes"].append({"url": h + p, "methode": "GET", "status": st, "antwort": (txt or "")[:300]})
    # Startseite + JS-Bundles nach Coupon-/Share-Begriffen durchsuchen
    muster = re.compile(r"[\w/\-\.]*(?:SaveCoupon|GetCoupon|LoadCoupon|couponCode|coupon_code|bookingCode|bet_slip|betslip|shareCoupon|\bbs=)[\w/\-\.=?]*", re.I)
    for h in HOSTS:
        st, html, u = _req(h + "/de", ctype=None)
        out["js"][h] = {"status": st, "final": u, "funde": sorted(set(muster.findall(html or "")))[:40]}
        scripts = re.findall(r'src="([^"]+\.js[^"]*)"', html or "")[:25]
        for s in scripts:
            url = s if s.startswith("http") else h + s
            st2, js, _ = _req(url, ctype=None)
            f = sorted(set(muster.findall(js or "")))[:30]
            if f:
                out["js"][url] = f
    p = Path(runs_dir) / f"coupon_test_{time.strftime('%Y-%m-%d_%H%M')}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("Coupon-Test:", p, [(x["url"], x["status"]) for x in out["probes"]])
