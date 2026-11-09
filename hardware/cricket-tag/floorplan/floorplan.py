"""Расстановка cricket-tag на пробной плате: реальные футпринты, DRC на перекрытия.

Не разводка, а проверка площади: детали ставятся по курятникам, DRC ищет
перекрытия (courtyards_overlap). Варианты и картинки — в README платы,
раздел «Размер платы»; текущий — w16b (D-27).

python3 floorplan.py w16b /tmp/fp.kicad_pcb    # w14, w14s, w16b, w18s
cp cricket-tag.kicad_pro /tmp/fp.kicad_pro; cp fp-lib-table /tmp/
kicad-cli pcb drc /tmp/fp.kicad_pcb -o /tmp/fp.rpt
Координаты платы: X поперёк (0..W), Y вдоль (0..L), антенна у Y=0.
"""
import math
import re
import sys
import uuid

import os
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STD = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
SOT235 = "Package_TO_SOT_SMD:SOT-23-5"


def fp_text(fp):
    lib, name = fp.split(":")
    path = f"{PROJ}/lib/cricket.pretty/{name}.kicad_mod" if lib == "cricket" else f"{STD}/{lib}.pretty/{name}.kicad_mod"
    return open(path).read()


def place(fp, ref, x, y, rot=0, side="F"):
    t = fp_text(fp)
    # имя с библиотекой и положение
    t = re.sub(r'^\(footprint "[^"]*"', f'(footprint "{fp}"\n\t(at {x} {y} {rot})', t, count=1)
    t = re.sub(r'\n\t\(version \d+\)\n\t\(generator "[^"]*"\)\n(\t\(generator_version "[^"]*"\)\n)?', "\n", t, count=1)
    t = re.sub(r'"(REF|U)\*\*"', f'"{ref}"', t, count=1)

    # ориентация площадок в файле платы абсолютная
    t = re.sub(r'(\(pad "[^"]*" \w+ \w+[^\n]*?\n?\s*)\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)',
               lambda m: f'{m.group(1)}(at {m.group(2)} {m.group(3)} {float(m.group(4) or 0) + rot:g})', t)
    # зоны в футпринте хранятся в абсолютных координатах платы
    zm = re.search(r"\(zone\s", t)
    if zm:
        zs = zm.start()
        c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))

        def tr(m):
            px, py = float(m.group(1)), float(m.group(2))
            return "(xy %g %g)" % (x + px * c + py * s, y - px * s + py * c)
        t = t[:zs] + re.sub(r"\(xy ([-\d.]+) ([-\d.]+)\)", tr, t[zs:])
    if side == "B":
        t = t.replace('(layer "F.Cu")', '(layer "B.Cu")', 1)
        for a, b in (("F.Cu", "B.Cu"), ("F.Paste", "B.Paste"), ("F.Mask", "B.Mask"), ("F.SilkS", "B.SilkS"),
                     ("F.CrtYd", "B.CrtYd"), ("F.Fab", "B.Fab")):
            t = t.replace(f'"{a}"', f'"{b}"')
    return t


BATTERY = (20.0, 10.0)  # 401020: длина × ширина


def board(parts, W, L, out, battery=BATTERY):
    pcb = open(f"{PROJ}/cricket-tag.kicad_pcb").read()
    edge = "".join(
        f'\t(gr_line (start {a}) (end {b}) (stroke (width 0.05) (type default)) (layer "Edge.Cuts"))\n'
        for a, b in [("0 0", f"{W} 0"), (f"{W} 0", f"{W} {L}"), (f"{W} {L}", f"0 {L}"), (f"0 {L}", "0 0")])
    body = "".join(place(*p) + "\n" for p in parts)
    bl, bw = battery
    bx0, by0 = (W - bw) / 2, L - bl
    bat = (f'\t(gr_rect (start {bx0} {by0}) (end {bx0 + bw} {L}) (stroke (width 0.15) (type dash))'
           f' (fill no) (layer "Dwgs.User"))\n')
    pcb = pcb.replace('\t(net 0 "")\n', '\t(net 0 "")\n' + body + edge + bat)
    open(out, "w").write(pcb)


def variant_w14():
    """14 мм шириной: модуль с антенной впереди, под ним кварц, излучатель, питание, разъёмы в хвосте."""
    W = 14
    L = 35.9
    p = [
        ("cricket:ANNA-B402_CornerAntenna", "U1", 3.95, 7.25),
        # полоса рядом с модулем (x 7,6..14)
        ("Package_LGA:LGA-12_2x2mm_P0.5mm", "U5", 9.0, 7.0),
        (C0402, "C15", 9.0, 4.8), (C0402, "C16", 9.0, 9.3),
        (R0402, "R10", 9.0, 3.7), (R0402, "R11", 9.0, 2.6),
        ("Button_Switch_SMD:SW_SPST_TS-1088-xR020", "SW1", 12.15, 3.9, 90),
        ("LED_SMD:LED_0603_1608Metric", "D2", 12.1, 8.6),
        # под модулем: развязка, кварц, ключ светодиода
        (C0402, "C6", 0.6, 12.0, 90), (C0402, "C7", 1.6, 12.0, 90),
        ("Crystal:Crystal_SMD_2012-2Pin_2.0x1.2mm", "Y1", 4.0, 12.0),
        (C0402, "C8", 6.2, 12.0, 90), (C0402, "C9", 7.2, 12.0, 90),
        (R0402, "R8", 8.7, 11.4), (R0402, "R9", 8.7, 12.6),
        ("Package_TO_SOT_SMD:SOT-23", "Q1", 11.8, 12.0),
        # излучатель и драйвер
        ("cricket:SameSky_CPT-9019A-SMT", "BZ1", 5.25, 18.6),
        ("cricket:Diodes_W-QFN2020-12_2x2mm_P0.4mm_EP1.0x1.0mm", "U4", 12.3, 15.2),
        (C0402, "C11", 11.2, 17.6, 90), (C0402, "C12", 12.2, 17.6, 90), (C0402, "C13", 13.2, 17.6, 90),
        (C0402, "C14", 11.2, 19.6, 90), (C0603, "C10", 12.7, 20.05, 90),
        (R0402, "R6", 12.2, 22.15), (R0402, "R7", 12.2, 23.1),
        # питание
        ("Package_TO_SOT_SMD:SOT-23-5", "U2", 2.15, 25.3),
        ("Package_TO_SOT_SMD:SOT-23-5", "U3", 6.5, 25.3),
        ("Diode_SMD:D_SOD-123", "D1", 9.9, 25.8, 90),
        (C0603, "C1", 11.9, 25.15, 90), (C0402, "C2", 13.3, 25.15, 90),
        (R0402, "R1", 0.6, 28.15, 90), (R0402, "R2", 1.6, 28.15, 90), (R0402, "R3", 2.6, 28.15, 90),
        (R0402, "R4", 3.6, 28.15, 90), (R0402, "R5", 4.6, 28.15, 90), (C0402, "C3", 5.6, 28.15, 90),
        (C0402, "C4", 6.6, 28.15, 90), (C0402, "C5", 7.6, 28.15, 90),
        # разъёмы в хвосте
        ("Connector_JST:JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal", "J1", 3.9, L - 3.28, 180),
        ("Connector_JST:JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal", "J2", 11.0, L - 3.28, 180),
    ]
    return p, W, L


WIRE = "Connector_Wire:SolderWirePad_1x01_SMD_1x2mm"
TP = "TestPoint:TestPoint_Pad_1.0x1.0mm"


def variant_w14s():
    """Как w14, но без разъёмов (D-26): площадки проводов J1, J2 и SWD J3 снизу, только медь.
    Аккумулятор до 15 мм длиной (401012, 401015) лежит снизу за площадками проводов."""
    p, W, _ = variant_w14()
    p = [x for x in p if x[1] not in ("J1", "J2")]
    L = 29.3
    p += BOTTOM_PADS_14
    return p, W, L, (15.0, 10.0)


BOTTOM_PADS_14 = [
    ("cricket:WirePads_1x04_P2.0mm", "J1", 4.2, 12.4, 0, "B"),
    ("cricket:WirePads_1x02_P2.0mm", "J2", 11.8, 12.4, 0, "B"),
    ("cricket:SWD_Pads_1x04_P2.54mm", "J3", 7.0, 24.0, 0, "B"),
]


def variant_w16b():
    """16 мм шириной, без разъёмов, излучатель CPT-1117-83 (лепестки вдоль платы) под модулем,
    питание и драйвер в колонке справа от него."""
    W, L = 16, 29.2
    p = [
        ("cricket:ANNA-B402_CornerAntenna", "U1", 3.95, 7.25),
        # полоса рядом с модулем
        ("Package_LGA:LGA-12_2x2mm_P0.5mm", "U5", 9.1, 7.0),
        (C0402, "C15", 9.1, 4.8), (C0402, "C16", 9.1, 9.3),
        (R0402, "R10", 9.1, 3.7), (R0402, "R11", 9.1, 2.6),
        ("Button_Switch_SMD:SW_SPST_TS-1088-xR020", "SW1", 14.15, 3.9, 90),
        ("LED_SMD:LED_0603_1608Metric", "D2", 14.3, 8.4),
        (R0402, "R8", 11.35, 6.0), (R0402, "R9", 11.35, 7.0),
        (R0402, "R6", 11.35, 8.0), (R0402, "R7", 11.35, 9.0),
        # под модулем: кварц, развязка; справа драйвер
        (C0402, "C6", 0.6, 11.9, 90), (C0402, "C7", 1.6, 11.9, 90),
        ("Crystal:Crystal_SMD_2012-2Pin_2.0x1.2mm", "Y1", 4.0, 11.9),
        (C0402, "C8", 6.2, 11.9, 90), (C0402, "C9", 7.2, 11.9, 90),
        (C0402, "C14", 8.2, 11.9, 90),
        ("cricket:Diodes_W-QFN2020-12_2x2mm_P0.4mm_EP1.0x1.0mm", "U4", 11.15, 12.2),
        (C0402, "C11", 13.1, 11.75, 90), (C0402, "C12", 14.1, 11.75, 90), (C0402, "C13", 15.1, 11.75, 90),
        # излучатель
        ("cricket:SameSky_CPT-1117-83-SMT", "BZ1", 4.95, 21.1),
        # колонка справа от излучателя
        ("Package_TO_SOT_SMD:SOT-23-5", "U2", 11.85, 15.4), (C0603, "C10", 15.0, 15.4, 90),
        ("Package_TO_SOT_SMD:SOT-23-5", "U3", 11.85, 18.85), (C0603, "C1", 15.0, 18.85, 90),
        ("Package_TO_SOT_SMD:SOT-23", "Q1", 11.75, 22.3),
        (C0402, "C2", 14.5, 22.3, 90), (C0402, "C4", 15.45, 22.3, 90),
        ("Diode_SMD:D_SOD-123", "D1", 12.25, 25.2), (C0402, "C5", 15.4, 25.2, 90),
        (R0402, "R1", 10.75, 26.9), (R0402, "R2", 12.75, 26.9), (R0402, "R3", 14.75, 26.9),
        (R0402, "R4", 10.75, 27.85), (R0402, "R5", 12.75, 27.85), (C0402, "C3", 14.75, 27.85),
        # снизу, только медь
        ("cricket:WirePads_1x04_P2.0mm", "J1", 4.2, 12.4, 0, "B"),
        ("cricket:WirePads_1x02_P2.0mm", "J2", 12.0, 12.4, 0, "B"),
        ("cricket:SWD_Pads_1x04_P2.54mm", "J3", 8.0, 24.0, 0, "B"),
    ]
    return p, W, L, (15.0, 10.0)


def variant_w18s():
    """18 мм шириной, без разъёмов: излучатель рядом с модулем, под ними всё остальное.
    Длина упирается в аккумулятор 401012: он не должен заходить под модуль."""
    W, L = 18, 22.8
    p = [
        ("cricket:ANNA-B402_CornerAntenna", "U1", 3.95, 7.25),
        ("cricket:SameSky_CPT-9019A-SMT", "BZ1", 12.35, 5.5, 90),
        # под модулем: кварц и развязка
        (C0402, "C6", 0.6, 11.9, 90), (C0402, "C7", 1.6, 11.9, 90),
        ("Crystal:Crystal_SMD_2012-2Pin_2.0x1.2mm", "Y1", 4.0, 11.9),
        (C0402, "C8", 6.2, 11.9, 90), (C0402, "C9", 7.2, 11.9, 90),
        # под излучателем: драйвер
        ("cricket:Diodes_W-QFN2020-12_2x2mm_P0.4mm_EP1.0x1.0mm", "U4", 9.2, 12.2),
        (C0402, "C11", 11.2, 11.75, 90), (C0402, "C12", 12.2, 11.75, 90), (C0402, "C13", 13.2, 11.75, 90),
        (C0402, "C14", 14.2, 11.75, 90), (C0603, "C10", 15.65, 12.25, 90),
        # питание слева
        ("Package_TO_SOT_SMD:SOT-23-5", "U2", 2.15, 14.85),
        ("Package_TO_SOT_SMD:SOT-23-5", "U3", 2.15, 18.35),
        ("Diode_SMD:D_SOD-123", "D1", 5.4, 15.5, 90),
        (C0603, "C1", 5.95, 18.65),
        (C0402, "C2", 5.4, 19.95), (C0402, "C4", 5.4, 20.92), (C0402, "C5", 5.4, 21.88),
        (R0402, "R1", 1.05, 20.6), (R0402, "R2", 3.05, 20.6), (R0402, "R3", 1.05, 21.6), (R0402, "R4", 3.05, 21.6),
        # справа: ключ светодиода, кнопка, акселерометр, светодиод
        ("Package_TO_SOT_SMD:SOT-23", "Q1", 9.75, 15.45),
        ("Button_Switch_SMD:SW_SPST_TS-1088-xR020", "SW1", 14.85, 15.5),
        ("Package_LGA:LGA-12_2x2mm_P0.5mm", "U5", 9.0, 18.6),
        (C0402, "C15", 10.8, 18.6, 90), (C0402, "C16", 11.8, 18.6, 90),
        (R0402, "R10", 12.8, 18.6, 90), (R0402, "R11", 13.8, 18.6, 90),
        ("LED_SMD:LED_0603_1608Metric", "D2", 16.3, 18.5),
        (R0402, "R6", 8.8, 20.6), (R0402, "R7", 8.8, 21.6),
        (R0402, "R5", 10.8, 20.6), (C0402, "C3", 10.8, 21.6),
        (R0402, "R8", 12.8, 20.6), (R0402, "R9", 12.8, 21.6),
    ]
    # снизу, только медь: провода полётника и аккумулятора перед аккумулятором, под излучателем
    for i, ref in enumerate(("P1", "P2", "P3", "P4", "P5", "P6")):
        p.append((WIRE, ref, 8.4 + 1.75 * i, 8.6, 0, "B"))
    for i, ref in enumerate(("TP1", "TP2", "TP3", "TP4")):
        p.append((TP, ref, 6.0 + 2.0 * i, 16.5, 0, "B"))
    return p, W, L, (12.0, 10.0)


if __name__ == "__main__":
    r = {"w14": variant_w14, "w14s": variant_w14s, "w18s": variant_w18s, "w16b": variant_w16b}[sys.argv[1]]()
    board(*r[:3], sys.argv[2], *r[3:])
    parts, W, L = r[:3]
    print(W, L)
