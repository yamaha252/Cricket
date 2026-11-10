#!/bin/sh
# Выходные файлы для JLCPCB в fab/: gerber + сверловка (zip), BOM и CPL в их формате.
# Запуск из любого каталога. Перед выгрузкой ERC и DRC должны быть чистыми.
set -e
cd "$(dirname "$0")"
PCB=cricket-tag.kicad_pcb
SCH=cricket-tag.kicad_sch
OUT=fab
q() { grep -v Fontconfig || true; }

rm -rf "$OUT"
mkdir -p "$OUT/gerbers"

kicad-cli pcb export gerbers "$PCB" -o "$OUT/gerbers/" \
  --layers F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts \
  --subtract-soldermask 2>&1 | q
kicad-cli pcb export drill "$PCB" -o "$OUT/gerbers/" --format excellon \
  --excellon-separate-th 2>&1 | q
(cd "$OUT/gerbers" && zip -q ../cricket-tag-gerbers.zip ./*)

kicad-cli sch export bom "$SCH" -o "$OUT/bom-kicad.csv" \
  --fields "Value,Reference,Footprint,LCSC Part" \
  --labels "Comment,Designator,Footprint,LCSC Part #" \
  --group-by "Value,Footprint,LCSC Part" --ref-range-delimiter "" --exclude-dnp 2>&1 | q

kicad-cli pcb export pos "$PCB" -o "$OUT/pos-kicad.csv" --format csv --units mm \
  --side front --exclude-dnp 2>&1 | q

# bom.csv, cpl.csv — для JLCPCB; bom-mpn.csv, cpl-kicad.csv — для других заводов.
# BOM: JLCPCB читает CSV не как UTF-8 («µ» → «碌», «Ω» → «惟»), поэтому в Comment
# только ASCII. Подбор идёт по LCSC Part #, Comment — для человека.
# CPL: KiCad Ref,Val,Package,PosX,PosY,Rot,Side -> JLCPCB Designator,Mid X,Mid Y,Layer,Rotation.
# Поправка поворота зависит от модели детали в библиотеке JLCPCB, а не от корпуса
# (U2 и U3 — оба SOT-23-5, а поправки разные), поэтому ключ — номер LCSC.
# Найдены по предпросмотру сборки JLCPCB 2026-11-10: метка первого вывода модели
# против треугольника на шелкографии. D2, U1, BZ1 там не проверены — смотреть
# в предпросмотре перед оплатой. Без поправки стоят пассивы, D1 (C8598), U4 (C510550).
python3 -I - "$OUT/bom-kicad.csv" "$OUT/pos-kicad.csv" "$OUT/bom.csv" "$OUT/cpl.csv" <<'EOF'
import csv, sys
bom_src, pos_src, bom_dst, cpl_dst = sys.argv[1:5]
ROT_FIX = {
    "C32574": 270,    # U2 TP4054, SOT-23-5
    "C2887324": 180,  # U3 TPS7A0233, SOT-23-5
    "C8545": 180,     # Q1 2N7002, SOT-23
    "C110926": 270,   # U5 LIS2DH12, LGA-12
}
# Производитель и номер производителя по номеру LCSC — для заводов без каталога LCSC
# (NextPCB и др.). Номера пассивов — из подбора BOM на JLCPCB 2026-11-10.
MPN = {
    "C22359733": ("Same Sky", "CPT-1117-83-SMT-TR"),
    "C19702": ("Samsung Electro-Mechanics", "CL10A106KP8NNNC"),
    "C52923": ("Samsung Electro-Mechanics", "CL05A105KA5NQNC"),
    "C1525": ("Samsung Electro-Mechanics", "CL05B104KO5NNNC"),
    "C23630": ("Samsung Electro-Mechanics", "CL10A225KO8NNNC"),
    "C8598": ("Changjiang Electronics Tech (CJ)", "B5819W SL"),
    "C2290": ("Hubei KENTO Elec", "KT-0603W"),
    "C8545": ("Changjiang Electronics Tech (CJ)", "2N7002"),
    "C26083": ("UNI-ROYAL", "0402WGF1004TCE"),
    "C22276": ("UNI-ROYAL", "0402WGF1504TCE"),
    "C25768": ("UNI-ROYAL", "0402WGF2202TCE"),
    "C11702": ("UNI-ROYAL", "0402WGF1001TCE"),
    "C25091": ("UNI-ROYAL", "0402WGF2200TCE"),
    "C25744": ("UNI-ROYAL", "0402WGF1002TCE"),
    "C720477": ("XUNPU", "TS-1088-AR02016"),
    "C44975104": ("Insight SiP", "ISP2454-LX-RS"),
    "C32574": ("TOPPOWER", "TP4054-42-SOT25R"),
    "C2887324": ("Texas Instruments", "TPS7A0233PDBVR"),
    "C510550": ("Diodes Incorporated", "PAM8904EGPR"),
    "C110926": ("STMicroelectronics", "LIS2DH12TR"),
}
lcsc, rows = {}, []
with open(bom_src, newline="", encoding="utf-8") as f, \
        open(bom_dst, "w", newline="", encoding="ascii") as g:
    w = csv.writer(g, quoting=csv.QUOTE_ALL)
    for i, r in enumerate(csv.reader(f)):
        if i:
            r[0] = r[0].replace("µ", "u").replace("Ω", "Ohm")
            for ref in r[1].split(","):
                lcsc[ref] = r[3]
            rows.append(r)
        w.writerow(r)
# BOM с номерами производителя: Designator, Quantity, Manufacturer, MPN, Description, Package, LCSC.
with open(bom_dst.replace("bom.csv", "bom-mpn.csv"), "w", newline="", encoding="ascii") as g:
    w = csv.writer(g, quoting=csv.QUOTE_ALL)
    w.writerow(["Designator", "Quantity", "Manufacturer", "Manufacturer Part Number",
                "Description", "Package", "LCSC Part #"])
    for comment, refs, fp, part in rows:
        man, mpn = MPN[part]
        w.writerow([refs, len(refs.split(",")), man, mpn, comment, fp.split(":")[-1], part])
with open(pos_src, newline="", encoding="utf-8") as f:
    pos = list(csv.DictReader(f))
with open(cpl_dst, "w", newline="", encoding="ascii") as g:
    w = csv.writer(g)
    w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    for r in pos:
        rot = (float(r["Rot"]) + ROT_FIX.get(lcsc.get(r["Ref"], ""), 0)) % 360
        w.writerow([r["Ref"], f'{float(r["PosX"]):.4f}mm', f'{float(r["PosY"]):.4f}mm',
                    "Top" if r["Side"] == "top" else "Bottom", f"{rot:g}"])
# CPL без поправок JLCPCB — повороты KiCad как есть, для других заводов.
with open(cpl_dst.replace("cpl.csv", "cpl-kicad.csv"), "w", newline="", encoding="ascii") as g:
    w = csv.writer(g)
    w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    for r in pos:
        w.writerow([r["Ref"], f'{float(r["PosX"]):.4f}mm', f'{float(r["PosY"]):.4f}mm',
                    "Top" if r["Side"] == "top" else "Bottom", f'{float(r["Rot"]) % 360:g}'])
EOF
rm "$OUT/pos-kicad.csv" "$OUT/bom-kicad.csv"
# NextPCB принимает файл расстановки только как zip/rar/xls/xlsx.
(cd "$OUT" && zip -q cpl-kicad.zip cpl-kicad.csv)
ls -l "$OUT"
