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
lcsc = {}
with open(bom_src, newline="", encoding="utf-8") as f, \
        open(bom_dst, "w", newline="", encoding="ascii") as g:
    w = csv.writer(g, quoting=csv.QUOTE_ALL)
    for i, r in enumerate(csv.reader(f)):
        if i:
            r[0] = r[0].replace("µ", "u").replace("Ω", "Ohm")
            for ref in r[1].split(","):
                lcsc[ref] = r[3]
        w.writerow(r)
with open(pos_src, newline="", encoding="utf-8") as f, \
        open(cpl_dst, "w", newline="", encoding="ascii") as g:
    w = csv.writer(g)
    w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    for r in csv.DictReader(f):
        rot = (float(r["Rot"]) + ROT_FIX.get(lcsc.get(r["Ref"], ""), 0)) % 360
        w.writerow([r["Ref"], f'{float(r["PosX"]):.4f}mm', f'{float(r["PosY"]):.4f}mm',
                    "Top" if r["Side"] == "top" else "Bottom", f"{rot:g}"])
EOF
rm "$OUT/pos-kicad.csv" "$OUT/bom-kicad.csv"
ls -l "$OUT"
