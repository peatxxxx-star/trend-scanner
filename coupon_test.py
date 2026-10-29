"""29.10.: Wettschein-Codes für die offenen Scheine des Tages erzeugen (keine Wette). runs/coupon_test_<Zeit>.json"""
import json, glob, time
from pathlib import Path
import betlabel


def run(runs_dir):
    f = sorted(x for x in glob.glob(str(Path(runs_dir) / "2026-*_*.json")) if not any(s in x for s in ("ergeb", "prewarm", "dump", "coupon", "quoten")))[-1]
    d = json.load(open(f))
    idx = {}
    for b, a in (("karten", "karten"), ("tore35", "tore"), ("ecken_fav", "ecken")):
        for t in (d.get(b) or {}).get("tipps") or []:
            idx[str(t["match_id"])] = (a, t)
    out = {"lauf": f, "zeit": time.strftime("%Y-%m-%d %H:%M"), "scheine": []}
    for tag, v in (d.get("scheine") or {}).items():
        for s in v.get("scheine") or []:
            legs = [idx[k] for k in s["tipps"] if k in idx]
            try:
                code, info = betlabel.wettschein_code(legs)
            except Exception as e:
                code, info = None, f"{type(e).__name__}: {e}"
            out["scheine"].append({"nr": s["nr"], "spiele": [t["spiel"] for a, t in legs], "code": code, "info": info})
    p = Path(runs_dir) / f"coupon_test_{time.strftime('%Y-%m-%d_%H%M')}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("Coupon-Test:", out["scheine"])


def partner_suche(runs_dir, code):
    """29.10.: BL-Code (von Lucio gespeichert) unter welchen partner-Werten auffindbar? Nur GetCoupon (lesen)."""
    out = {"code": code, "treffer": [], "proben": {}}
    for p in [None] + list(range(0, 400)):
        pl = {"Guid": code, "Lng": "de"}
        if p is not None:
            pl["partner"] = p
        try:
            j = betlabel._post(betlabel.WEB + "GetCoupon", pl)
        except Exception as e:
            j = {"Error": f"{type(e).__name__}: {e}"}
        key = (j.get("Error") or "")[:60] + ("|OK" if j.get("Success") else "")
        out["proben"].setdefault(key, []).append(p)
        if j.get("Success") or (j.get("Value") and not j.get("Error")):
            out["treffer"].append({"partner": p})          # keine Antwort speichern: enthält die BL-Kundennummer
            if len(out["treffer"]) >= 3:
                break
    p = Path(runs_dir) / f"coupon_partner_{time.strftime('%Y-%m-%d_%H%M')}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("Coupon-Partner:", out["treffer"][:1], {k: len(v) for k, v in out["proben"].items()})
