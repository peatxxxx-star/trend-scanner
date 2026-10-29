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
