"""24.10. (Lucio): stündlicher Check für heute.
  --abruf      offene Beine laufender Scheine, die vorbei sind -> Event-IDs -> Ergebnis-Abruf auslösen
  --auswerten  neueste Ergebnisse in wetten.csv eintragen, dann 3er-Check; Telegram NUR wenn ein neuer 3er möglich ist
"""
import csv, glob, json, re, subprocess, sys, time, unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

REPO = "/home/claude/trend-scanner"
SP = "auswertung"
B = ZoneInfo("Europe/Berlin")
TRAILER = "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01BZFq9zKc67xzrUp5uM11kY"


def git(*a):
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True)


def push(msg, files):
    git("add", *files)
    git("commit", "-q", "-m", msg + TRAILER)
    for _ in range(4):
        if git("push", "-q").returncode == 0:
            return True
        git("pull", "-q", "--rebase")
    return False


def norm(x):
    x = unicodedata.normalize("NFKD", x or "").encode("ascii", "ignore").decode().lower()
    return set(w for w in re.findall(r"[a-z]+", x) if len(w) > 2 and w not in ("u19", "u21", "fc", "club", "the", "reserves"))


def lade_csv():
    with open(f"{REPO}/wetten.csv", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def schreibe_csv(head, rows):
    with open(f"{REPO}/wetten.csv", "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([head] + rows)


def event_id(spiel):
    a, _, b = spiel.partition("–")
    ta, tb = norm(a), norm(b)
    for f in sorted(glob.glob(f"{REPO}/runs/2026-*_*.json"), reverse=True)[:80]:
        if "ergeb" in f or "prewarm" in f:
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        for h in d.get("hits", []):
            m = h["match"]
            if (norm(m["home"]) & ta) and (norm(m["away"]) & tb):
                return str(m["id"])
    return None


def offene_beine(rows, H):
    jetzt = datetime.now(B)
    out = []
    for i, r in enumerate(rows):
        if r[H["schein_status"]] != "offen" or r[H["tipp_status"]] != "offen":
            continue
        try:
            ko = datetime.strptime(r[H["anstoss"]][:16], "%Y-%m-%d %H:%M").replace(tzinfo=B)
        except ValueError:
            continue
        if (jetzt - ko).total_seconds() > 115 * 60:
            out.append(i)
    return out


def abruf():
    git("pull", "-q", "--rebase")
    head, rows = lade_csv(); H = {k: i for i, k in enumerate(head)}
    ids = {}
    for i in offene_beine(rows, H):
        eid = event_id(rows[i][H["spiel"]])
        if eid:
            ids[eid] = rows[i][H["spiel"]]
        else:
            print("keine Event-ID:", rows[i][H["spiel"]])
    if not ids:
        print("ABRUF: nichts offen"); return
    open(f"{REPO}/scan_now", "w").write(datetime.utcnow().isoformat())
    json.dump({"t": time.time(), "ids": ids}, open(f"{SP}/abruf.json", "w"))
    push("Ergebnis-Abruf: " + ",".join(ids), ["scan_now"])
    print("ABRUF:", ids)


WERT = (("Gelbe Karten", "yellowcards"), ("Ecken", "corners"), ("Abseits", "offsides"), ("Tore", "goals"))


def bewerte(markt, linie, erg):
    team = None
    if ":" in markt:
        team, markt = [x.strip() for x in markt.split(":", 1)]
    key = next((k for w, k in WERT if w in markt), None)
    if not key:
        return None, None
    if key == "goals" and erg.get("ss") and "-" in erg["ss"]:
        pair = [int(x) for x in erg["ss"].split("-")[:2]]
    else:
        pair = (erg.get("slim") or {}).get(key)
    if not pair or pair[0] is None or min(pair) < 0:
        return None, None
    if team:
        th, ta = norm(erg.get("home")), norm(erg.get("away"))
        tt = norm(team)
        if tt & th and not tt & ta:
            v = pair[0]
        elif tt & ta and not tt & th:
            v = pair[1]
        else:
            return None, None
    else:
        v = pair[0] + pair[1]
    L = float(linie)
    hit = v > L if "über" in markt else v < L
    return hit, v


def auswerten():
    git("pull", "-q", "--rebase")
    try:
        ab = json.load(open(f"{SP}/abruf.json"))
    except Exception:
        ab = None
    neu = []
    if ab:
        erg = {}
        for f in sorted(glob.glob(f"{REPO}/runs/ergebnisse_*.json")):
            for k, v in json.load(open(f)).items():
                if str(v.get("time_status")) == "3":
                    erg[str(k)] = v
        head, rows = lade_csv(); H = {k: i for i, k in enumerate(head)}
        for i in offene_beine(rows, H):
            r = rows[i]
            eid = next((e for e, s in ab["ids"].items() if s == r[H["spiel"]]), None)
            if not eid or eid not in erg:
                continue
            hit, v = bewerte(r[H["markt"]], r[H["linie"]], erg[eid])
            if hit is None:
                print("nicht auswertbar:", r[H["spiel"]], r[H["markt"]]); continue
            r[H["tipp_status"]] = "gewonnen" if hit else "verloren"
            r[H["ergebnis"]] = f'{erg[eid].get("ss")}, Wert {v} (Auto-Abruf)'
            neu.append(f'{"✅" if hit else "❌"} {r[H["spiel"]]}: {r[H["markt"]]} {r[H["linie"]]} → {v}')
        # Scheinstatus
        sch = {}
        for r in rows:
            sch.setdefault(r[H["schein"]], []).append(r)
        for k, rs in sch.items():
            if rs[0][H["schein_status"]] != "offen":
                continue
            st = [r[H["tipp_status"]] for r in rs]
            if "verloren" in st:
                for r in rs: r[H["schein_status"]] = "verloren"; r[H["auszahlung"]] = "0"
                neu.append(f"❌ Schein {k} verloren")
            elif all(s == "gewonnen" for s in st):
                for r in rs:
                    r[H["schein_status"]] = "gewonnen"; r[H["auszahlung"]] = f'{float(r[H["einsatz"]]) * float(r[H["gesamtquote"]]):.2f}'
                neu.append(f"✅ Schein {k} GEWONNEN ({rs[0][H['auszahlung']]} €)")
        if neu:
            schreibe_csv(head, rows)
            push("Auto-Auswertung: " + "; ".join(n[:60] for n in neu[:3]), ["wetten.csv"])
        import os; os.remove(f"{SP}/abruf.json")
    print("ERGEBNISSE:", *neu, sep="\n  ")
    # 3er-Check
    out = subprocess.run([sys.executable, f"{SP}/check3er.py"], cwd=REPO, capture_output=True, text=True).stdout
    print(out)
    frei = []
    for l in out.splitlines():
        if l.startswith("TG|"):
            _, ko, spiel, tipp, q = l.split("|", 4)
            if spiel not in [f[1] for f in frei]:
                frei.append((ko, spiel, tipp, q))
    try:
        gemeldet = set(json.load(open(f"{SP}/gemeldet.json")))
    except Exception:
        gemeldet = set()
    neu_spiele = [f for f in frei if f[1] not in gemeldet]
    if len(frei) >= 3 and neu_spiele:
        def qv(q): return float(re.search(r"@([\d.]+)", q).group(1))
        sch = frei[:3]
        gq = 1.0
        for f in sch: gq *= qv(f[3])
        lines = [f"🔔 Neuer 3er möglich ({len(frei)} freie Spiele)", "", f"Schein (nach Anstoß), Quote ≈ {gq:.2f}:"]
        lines += [f"• {f[0]} {f[1]}: {f[2]} {f[3]}" for f in sch]
        if len(frei) > 3:
            lines += ["", "Weitere freie:"] + [f"• {f[0]} {f[1]}: {f[2]} {f[3]}" for f in frei[3:]]
        if neu:
            lines += ["", "Ergebnisse:"] + [f"• {n}" for n in neu]
        txt = "\n".join(lines)
        open(f"{REPO}/claude_msg.txt", "w").write(txt + "\n")
        push("Claude: neuer 3er möglich", ["claude_msg.txt"])
        json.dump(sorted(gemeldet | {f[1] for f in frei}), open(f"{SP}/gemeldet.json", "w"))
        print("TELEGRAM:\n" + txt)
    else:
        print(f"KEIN TELEGRAM (frei {len(frei)}, neu {len(neu_spiele)})")


if __name__ == "__main__":
    {"--abruf": abruf, "--auswerten": auswerten}[sys.argv[1]]()
