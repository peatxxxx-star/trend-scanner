import csv, math, sys
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
pdfmetrics.registerFont(TTFont("DV", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DVB", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
OUT = sys.argv[1]
SCHEINE = sys.argv[2].split(",")
rows = list(csv.DictReader(open("/home/claude/trend-scanner/wetten.csv", encoding="utf-8"))) + list(csv.DictReader(open("/home/claude/trend-scanner/spass_wetten.csv", encoding="utf-8")))
LBL = {"SPASS-2026-10-24-A": "Spaß 2er", "SPASS-2026-10-24-B": "Spaß BL"}
def lab(k, kurz=True):
    if k in LBL: return LBL[k]
    return k[-1] if k[8:10] == "24" else k[-1] + (" (23.)" if kurz else " (23.10.)")
rows = [r for r in rows if r["schein"] in SCHEINE]
WORT = {"Ecken": ("Ecken", "Eckstöße"), "Gelbe Karten": ("Gelbe", "Gelbe Karten"), "Abseits": ("Abseits", "Abseitsstellungen"), "Tore": ("Tore", "Tore")}
def info(r):
    markt, L = r["markt"], float(r["linie"])
    team = None
    if ":" in markt:
        team, markt = [x.strip() for x in markt.split(":", 1)]
    art = next(k for k in WORT if k in markt)
    unter = "unter" in markt
    n = math.floor(L) if unter else math.ceil(L)
    bed = f"höchstens {n}" if unter else f"mindestens {n}"
    home = r["spiel"].split("–")[0]
    if team:
        seite = "1." if team.split()[0].lower() in home.lower() else "2."
        bl = f"Gesamtzahl {seite} {WORT[art][1]} {L:g} {'Unter' if unter else 'Über'}"
        txt = f"{team}: {bed} {WORT[art][0]}"
    else:
        bl = f"Gesamtzahl {WORT[art][1] if art!='Tore' else ''} {L:g} {'Unter' if unter else 'Über'}".replace("  ", " ")
        txt = f"Spiel gesamt: {bed} {WORT[art][0]}"
    return txt, bl
ss = getSampleStyleSheet()
P = ParagraphStyle("p", fontName="DV", fontSize=8.5, leading=10.5)
PB = ParagraphStyle("pb", parent=P, fontName="DVB")
H = ParagraphStyle("h", fontName="DVB", fontSize=15, leading=19, spaceAfter=4)
H2 = ParagraphStyle("h2", fontName="DVB", fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=4)
S = ParagraphStyle("s", fontName="DV", fontSize=9, textColor=colors.HexColor("#555555"))
STAT = {"gewonnen": ("✓ durch", "#1a7f37"), "verloren": ("✗ verloren", "#c62828"), "offen": ("offen", "#333333")}
doc = SimpleDocTemplate(OUT, pagesize=landscape(A4), leftMargin=28, rightMargin=28, topMargin=26, bottomMargin=26)
st = [Paragraph(sys.argv[3], H), Paragraph(sys.argv[4] + " · 1. = Heimteam, 2. = Gastteam, Gesamtzahl = beide Teams · Gelb-Rot/Rot zählt nicht als Gelbe", S), Paragraph("Zeitplan – alle Beine nach Anstoß", H2)]
data = [[Paragraph(x, PB) for x in ("Anstoß", "Schein", "Spiel", "Liga", "Was muss passieren", "So steht's bei BetLabel", "Quote", "Status")]]
for r in sorted(rows, key=lambda r: r["anstoss"]):
    txt, bl = info(r)
    s, col = STAT.get(r["tipp_status"], (r["tipp_status"], "#333333"))
    ko = r["anstoss"][11:16] if len(r["anstoss"]) > 10 else "–"
    if r["anstoss"][:10] != "2026-10-24": ko = r["anstoss"][8:10] + "." + r["anstoss"][5:7] + ". " + ko
    data.append([Paragraph(ko, PB), Paragraph(lab(r["schein"]), PB), Paragraph(r["spiel"], P), Paragraph(r["wettbewerb"], P),
                 Paragraph(txt, PB), Paragraph(bl, P), Paragraph(r["quote"].replace(".", ","), P),
                 Paragraph(f'<font color="{col}">{s}</font>' + (f'<br/><font size="7">{r["ergebnis"]}</font>' if r["ergebnis"] else ""), P)])
t = Table(data, colWidths=[56, 44, 142, 104, 135, 142, 40, 119], repeatRows=1)
t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8d0da")),
                       ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")])]))
st.append(t)
st.append(Paragraph("Scheine im Überblick", H2))
sch = {}
for r in rows: sch.setdefault(r["schein"], []).append(r)
d2 = [[Paragraph(x, PB) for x in ("Schein", "Spiele", "Einsatz", "Quote", "Auszahlung", "Status")]]
for k in SCHEINE:
    if k not in sch: continue
    rs = sch[k]; s, col = STAT.get(rs[0]["schein_status"], (rs[0]["schein_status"], "#333"))
    beine = " · ".join(f'{r["spiel"].split("–")[0].strip()} ' + {"gewonnen": "✓", "verloren": "✗"}.get(r["tipp_status"], "(offen)") for r in sorted(rs, key=lambda r: r["anstoss"]))
    e = float(rs[0]["einsatz"]); q = float(rs[0]["gesamtquote"])
    d2.append([Paragraph(lab(k, False), PB), Paragraph(beine, P), Paragraph(f"{e:.2f} €".replace(".", ","), P), Paragraph(f"{q:.3f}".replace(".", ","), P),
               Paragraph(f"{e*q:.2f} €".replace(".", ","), PB), Paragraph(f'<font color="{col}">{s}</font>', PB)])
t2 = Table(d2, colWidths=[80, 390, 55, 50, 70, 80])
t2.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8d0da")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
st.append(t2)
doc.build(st)
print("ok", OUT)
