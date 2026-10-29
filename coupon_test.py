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
    # ein echtes Ereignis (1X2 Heimsieg) aus einem anstehenden Fußballspiel
    ev = None
    try:
        spiele = betlabel.lade_spiele()
        for g in spiele:
            d = betlabel._spiel_detail(g["I"])
            for grp in d.get("GE") or []:
                if grp.get("G") == 1 and grp.get("E") and grp["E"][0]:
                    e0 = grp["E"][0][0]
                    ev = {"GameId": d.get("I"), "Type": e0.get("T"), "Coef": e0.get("C"), "Param": e0.get("P", 0),
                          "PlayerId": 0, "Kind": 1, "Expired": 0, "Price": 0, "InstrumentId": 0, "Seconds": 0, "PV": None}
                    out["ereignis"] = {"spiel": f"{g.get('O1')} – {g.get('O2')}", **ev}
                    break
            if ev:
                break
    except Exception as e:
        out["ereignis_fehler"] = f"{type(e).__name__}: {e}"
    codes = []
    varianten = []
    for kind in (1, 3):
        e = dict(ev or {}, Kind=kind)
        varianten += [("wrap", {"Coupon": {"Events": [e], "Lng": "de", "Vid": 0, "partner": 1}}),
                      ("flach", {"Events": [e], "Lng": "de", "Vid": 0, "partner": 1, "Summ": 0, "CfView": 0}),
                      ("flach_ohnepartner", {"Events": [e], "Lng": "de", "Vid": 0})]
    for h in HOSTS[:1]:
        for name, pl in varianten:
            st, txt, u = _req(h + "/web-api/LiveUtil/SaveCoupon", data=json.dumps(pl).encode())
            out["probes"].append({"url": h + "/web-api/LiveUtil/SaveCoupon", "variante": f"{name} kind={pl.get('Events', pl.get('Coupon', {}).get('Events'))[0].get('Kind')}", "status": st, "antwort": (txt or "")[:400]})
            try:
                j = json.loads(txt)
                if j.get("Success") and (j.get("Value") or j.get("Id")):
                    codes.append(j.get("Value") or j.get("Id"))
            except Exception:
                pass
        for c in codes[:1]:
            c2 = c.get("Id") if isinstance(c, dict) else c
            for p, data in ((f"/web-api/LiveUtil/GetCoupon?Guid={c2}&lng=de&partner=1", None),
                            (f"/web-api/LiveUtil/GetCoupon?id={c2}&lng=de&partner=1", None),
                            ("/web-api/LiveUtil/GetCoupon", json.dumps({"Guid": c2, "Lng": "de", "partner": 1}).encode())):
                st, txt, u = _req(h + p, data=data)
                out["probes"].append({"url": h + p, "status": st, "antwort": (txt or "")[:600]})
    out["codes"] = codes
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
