#!/usr/bin/env python3
"""Генератор символа и футпринта u-blox ANNA-B402 для библиотеки cricket.

Источники:
- datasheet ANNA-B402 UBX-20032372 R06: рис. 3 (распиновка, вид сверху),
  рис. 5 и 6 (корпус, вид снизу), табл. 4 (назначение выводов);
- руководство по интеграции ANNA-B4 UBX-21000517 R08, приложение B.1,
  рис. 33 и 34 (антенна, модуль в углу платы).

Координаты в футпринте — вид сверху, начало в центре модуля, ось Y вниз
(как в KiCad). Вывод 1 в левом верхнем углу, противовес уходит от него вверх,
за край корпуса. Модуль ставится так, чтобы верхний и левый края корпуса
смотрели на кромки платы.

Запуск: python3 gen_anna_b402.py. Перезаписывает
cricket.pretty/ANNA-B402_CornerAntenna.kicad_mod и символ ANNA-B402 в
cricket.kicad_sym; другие символы библиотеки не трогает. Правки, сделанные
в редакторе KiCad, при повторном запуске теряются.
"""

import os
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
NS = uuid.UUID("6f1c2a7e-3c1d-4b8e-9a51-0c0ffee0b402")


def uid(name):
    return str(uuid.uuid5(NS, name))


# ---------------------------------------------------------------- геометрия
BODY = 6.5           # корпус 6,5 × 6,5 мм (рис. 6)
H = BODY / 2
PAD = 0.35           # 52 площадки 0,35 × 0,35
PAD_C = 0.42         # 4 центральные площадки 0,42 × 0,42
EDGE = 2.84          # E1 = D1 = 5,68: центры крайних рядов
INNER = 2.19         # внутренние столбцы: 1,06 от края корпуса
P = 0.65             # шаг

# Столбец выводов 1…9 (левый край, вид сверху) и 35…27 (правый край):
# 1 и 2 с шагом 0,65, между 2 и 3 — 0,942, дальше шаг 0,65;
# от 9 до нижнего ряда 0,188 (рис. 5).
COL_Y = [-EDGE, -EDGE + P]
COL_Y += [COL_Y[1] + 0.942 + i * P for i in range(7)]

pads = {}
for i, y in enumerate(COL_Y):
    pads[1 + i] = (-EDGE, y, PAD)        # 1…9
    pads[35 - i] = (EDGE, y, PAD)        # 35…27
# Нижний ряд 14…20, y = 2,84
for i in range(7):
    pads[14 + i] = (-1.95 + i * P, EDGE, PAD)
# Ряд 21…26, y = 2,19
for i in range(6):
    pads[21 + i] = (-1.625 + i * P, EDGE - P, PAD)
# Верхний внутренний ряд 46…40, y = −2,19 + 0,755
for i in range(7):
    pads[46 - i] = (-1.95 + i * P, -EDGE + P + 0.755, PAD)
# Второй ряд 52…47, на 0,65 ниже
for i in range(6):
    pads[52 - i] = (-1.625 + i * P, -EDGE + P + 0.755 + P, PAD)
# Внутренние столбцы: 10…13 слева, 39…36 справа; 36 и 13 в 1,572 от низа
for i in range(4):
    y = H - 1.572 - (3 - i) * P
    pads[10 + i] = (-INNER, y, PAD)
    pads[39 - i] = (INNER, y, PAD)
# Центральные площадки GND: от ряда 47…52 до 56 — 1,037, 56→55 — 0,9,
# 55→54 по X — 1,04
yc1 = -EDGE + P + 0.755 + P + 1.037
pads[53] = (-0.52, yc1, PAD_C)
pads[56] = (0.52, yc1, PAD_C)
pads[54] = (-0.52, yc1 + 0.9, PAD_C)
pads[55] = (0.52, yc1 + 0.9, PAD_C)

assert sorted(pads) == list(range(1, 57)), sorted(pads)

# Противовес (рис. 33, повёрнут на 180°): полоска 0,5 мм, 0,16…0,66 мм
# от края корпуса со стороны вывода 1; вверх до 3,5 мм за корпусом, затем
# вдоль границы зоны до 5,5 мм от края, на конце отросток 0,5 мм вниз
# до 2 мм от корпуса.
CP_IN, CP_OUT = 0.16, 0.66
x0, x1 = -H + CP_IN, -H + CP_OUT
cp = [
    (x0, pads[1][1]),
    (x0, -H - 3.5),
    (-H + 5.5, -H - 3.5),
    (-H + 5.5, -H - 2.0),
    (-H + 5.0, -H - 2.0),
    (-H + 5.0, -H - 3.0),
    (x1, -H - 3.0),
    (x1, pads[1][1]),
]

# Зона без земли и без дорожек (рис. 33 и 34, одинакова для всех слоёв,
# противовес на верхнем слое входит в футпринт): всё за краем корпуса со
# стороны антенны до кромки (u-blox: 4 мм от корпуса) и вырез под модулем
# 3,6 × 1,5 мм у вывода 1. Зона продлена на 1 мм влево за корпус, чтобы
# перекрыть полосу до боковой кромки.
REF_EDGE_END = 4.0     # кромка платы от корпуса со стороны антенны, рис. 34
REF_EDGE_SIDE = 0.7    # кромка сбоку, по рисунку ≈0,7 мм, не образмерено
KO = [
    (-H - 1.0, -H + 1.5),
    (-H + 3.6, -H + 1.5),
    (-H + 3.6, -H),
    (H, -H),
    (H, -H - REF_EDGE_END - 0.25),
    (-H - 1.0, -H - REF_EDGE_END - 0.25),
]


def f(v):
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def footprint():
    name = "ANNA-B402_CornerAntenna"
    o = []
    a = o.append
    a(f'(footprint "{name}"')
    a('\t(version 20240108)')
    a('\t(generator "cricket_gen_anna_b402")')
    a('\t(layer "F.Cu")')
    a('\t(descr "u-blox ANNA-B402 LGA-56 6,5x6,5 мм, встроенная антенна, модуль в углу платы: '
      'противовес на ANT_PCB и зона без меди по UBX-21000517 R08 прил. B.1")')
    a('\t(tags "u-blox ANNA-B4 nRF52833 BLE LGA")')
    a('\t(property "Reference" "U**" (at 4.6 0 90) (layer "F.SilkS")'
      f' (uuid "{uid("ref")}") (effects (font (size 0.8 0.8) (thickness 0.15))))')
    a(f'\t(property "Value" "{name}" (at 0 4.3 0) (layer "F.Fab")'
      f' (uuid "{uid("val")}") (effects (font (size 0.8 0.8) (thickness 0.12))))')
    a('\t(property "Footprint" "" (at 0 0 0) (layer "F.Fab") (hide yes)'
      f' (uuid "{uid("fpf")}") (effects (font (size 1.27 1.27))))')
    a('\t(property "Datasheet" "https://content.u-blox.com/sites/default/files/ANNA-B402_DataSheet_UBX-20032372.pdf"'
      f' (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{uid("ds")}") (effects (font (size 1.27 1.27))))')
    a('\t(property "Description" "" (at 0 0 0) (layer "F.Fab") (hide yes)'
      f' (uuid "{uid("desc")}") (effects (font (size 1.27 1.27))))')
    a('\t(attr smd)')

    def line(x1_, y1_, x2_, y2_, layer, w, key):
        a(f'\t(fp_line (start {f(x1_)} {f(y1_)}) (end {f(x2_)} {f(y2_)})'
          f' (stroke (width {w}) (type solid)) (layer "{layer}") (uuid "{uid(key)}"))')

    # F.Fab: корпус со скосом у вывода 1
    ch = 0.6
    fab = [(-H + ch, -H), (H, -H), (H, H), (-H, H), (-H, -H + ch), (-H + ch, -H)]
    for i in range(len(fab) - 1):
        line(*fab[i], *fab[i + 1], "F.Fab", 0.1, f"fab{i}")
    # F.Fab: противовес контуром, чтобы был виден на сборочном слое
    for i in range(len(cp)):
        line(*cp[i], *cp[(i + 1) % len(cp)], "F.Fab", 0.05, f"fabcp{i}")

    # F.SilkS: контур корпуса с разрывом над противовесом, метка вывода 1
    s = H + 0.11
    gap_r = x1 + 0.3
    line(gap_r, -s, s, -s, "F.SilkS", 0.12, "s_top")
    line(s, -s, s, s, "F.SilkS", 0.12, "s_right")
    line(s, s, -s, s, "F.SilkS", 0.12, "s_bot")
    line(-s, s, -s, -H + 1.5, "F.SilkS", 0.12, "s_left")
    a(f'\t(fp_circle (center {f(-s - 0.3)} {f(pads[1][1])}) (end {f(-s - 0.3 + 0.1)} {f(pads[1][1])})'
      f' (stroke (width 0.2) (type solid)) (fill solid) (layer "F.SilkS") (uuid "{uid("pin1")}"))')

    # F.CrtYd: корпус + 0,25 мм и вся антенная зона до кромки по u-blox
    c = H + 0.25
    ytop = -H - REF_EDGE_END
    crt = [(-c, ytop), (c, ytop), (c, c), (-c, c), (-c, ytop)]
    for i in range(4):
        line(*crt[i], *crt[i + 1], "F.CrtYd", 0.05, f"crt{i}")

    # Cmts.User: положение кромок платы в референс-дизайне u-blox
    ey = -H - REF_EDGE_END
    ex = -H - REF_EDGE_SIDE
    line(ex, ey, ex + 7.5, ey, "Cmts.User", 0.05, "edge_end")
    line(ex, ey, ex, ey + 9.0, "Cmts.User", 0.05, "edge_side")
    a(f'\t(fp_text user "кромка по u-blox: 4 мм от корпуса, сбоку ≈0,7 мм" (at {f(ex + 3.9)} {f(ey - 0.5)} 0)'
      f' (layer "Cmts.User") (uuid "{uid("edge_txt")}") (effects (font (size 0.4 0.4) (thickness 0.06))))')
    a(f'\t(fp_text user "${{REFERENCE}}" (at 0 -1.2 0) (layer "F.Fab") (uuid "{uid("fabref")}")'
      ' (effects (font (size 0.8 0.8) (thickness 0.12))))')

    # Площадки модуля
    for n in range(1, 57):
        x, y, sz = pads[n]
        a(f'\t(pad "{n}" smd rect (at {f(x)} {f(y)}) (size {f(sz)} {f(sz)})'
          f' (layers "F.Cu" "F.Paste" "F.Mask") (uuid "{uid(f"pad{n}")}"))')

    # Противовес: медь без маски и пасты, тот же номер, что у ANT_PCB
    px, py, _ = pads[1]
    pts = " ".join(f"(xy {f(x - px)} {f(y - py)})" for x, y in cp)
    a(f'\t(pad "1" smd custom (at {f(px)} {f(py)}) (size 0.3 0.3) (layers "F.Cu")'
      ' (zone_connect 0)'
      ' (options (clearance outline) (anchor rect))'
      f' (primitives (gr_poly (pts {pts}) (width 0) (fill yes)))'
      f' (uuid "{uid("cp_pad")}"))')

    # Зона без меди и дорожек на обоих слоях
    pts = " ".join(f"(xy {f(x)} {f(y)})" for x, y in KO)
    a(f'\t(zone (net 0) (net_name "") (layers "F.Cu" "B.Cu") (uuid "{uid("ko")}") (name "ANNA_ANT_KEEPOUT")'
      ' (hatch edge 0.5) (connect_pads (clearance 0)) (min_thickness 0.25) (filled_areas_thickness no)'
      ' (keepout (tracks not_allowed) (vias not_allowed) (pads allowed) (copperpour not_allowed) (footprints allowed))'
      ' (placement (enabled no) (sheetname ""))'
      ' (fill (thermal_gap 0.5) (thermal_bridge_width 0.5))'
      f' (polygon (pts {pts})))')
    a(')')
    return "\n".join(o) + "\n"


# ------------------------------------------------------------------ символ
# Выводы, которые datasheet помечает «standard drive, low-frequency I/O only»
LF = {19, 20, 22, 23, 27, 28, 29, 30, 38, 39, 47, 51}

GPIO = [  # (номер, имя) по порядку портов, правая сторона
    (20, "P0.02/AIN0"), (19, "P0.03/AIN1"), (25, "P0.04/AIN2"), (24, "P0.05/AIN3"),
    (32, "P0.06"), (48, "P0.07"), (50, "P0.08"), (22, "P0.09/NFC1"), (23, "P0.10/NFC2"),
    (14, "P0.11"), (15, "P0.12"), (52, "P0.13"), (11, "P0.14"), (40, "P0.15"),
    (36, "P0.16"), (49, "P0.17"), (38, "P0.19"), (10, "P0.20"), (26, "P0.21"),
    (37, "P0.22"), (39, "P0.23"), (33, "P0.26"), (31, "P0.27"), (30, "P0.28/AIN4"),
    (29, "P0.29/AIN5"), (28, "P0.30/AIN6"), (27, "P0.31/AIN7"), (51, "P1.01"),
    (47, "P1.07"), (13, "P1.09"),
]
LEFT = [  # (y, номер, имя, тип)
    (36.83, 9, "VCC", "power_in"),
    (34.29, 21, "VBUS", "power_in"),
    (29.21, 12, "P0.18/~{RESET}", "bidirectional"),
    (26.67, 42, "SWDIO", "bidirectional"),
    (24.13, 41, "SWDCLK", "input"),
    (21.59, 16, "P1.00/SWO", "bidirectional"),
    (16.51, 17, "P0.00/XL1", "bidirectional"),
    (13.97, 18, "P0.01/XL2", "bidirectional"),
    (8.89, 6, "ANT", "passive"),
    (6.35, 5, "ANT_INT", "passive"),
    (1.27, 1, "ANT_PCB", "passive"),
    (-1.27, 2, "ANT_GND1", "passive"),
    (-3.81, 3, "ANT_GND2", "passive"),
    (-8.89, 34, "D+", "bidirectional"),
    (-11.43, 35, "D-", "bidirectional"),
]
GND = [4, 7, 8, 43, 44, 45, 46, 53, 54, 55, 56]


def symbol():
    name = "ANNA-B402"
    lf = ", ".join(str(n) for n in sorted(LF))
    desc = ("u-blox ANNA-B402 open CPU, nRF52833, BLE 5.1 + Coded PHY, встроенная антенна, "
            f"LGA-56 6,5x6,5 мм. Выводы только для низкой частоты и слабого тока: {lf}. "
            "ANT_PCB — к противовесу (в футпринте), ANT_GND1/2 не подключать при установке в углу, "
            "ANT соединить с ANT_INT.")
    o = []
    a = o.append

    def prop(k, v, x, y, hide=False, key=None):
        h = " (hide yes)" if hide else ""
        a(f'\t\t(property "{k}" "{v}" (at {f(x)} {f(y)} 0){h}'
          f' (effects (font (size 1.27 1.27)){" (justify left)" if not hide else ""}))')

    a('(kicad_symbol_lib')
    a('\t(version 20231120)')
    a('\t(generator "cricket_gen_anna_b402")')
    a('\t(generator_version "1.0")')
    a(f'\t(symbol "{name}" (exclude_from_sim no) (in_bom yes) (on_board yes)')
    prop("Reference", "U", -15.24, 40.64)
    prop("Value", "ANNA-B402-00B", -15.24, -43.18)
    prop("Footprint", "cricket:ANNA-B402_CornerAntenna", 0, 0, True)
    prop("Datasheet", "https://content.u-blox.com/sites/default/files/ANNA-B402_DataSheet_UBX-20032372.pdf", 0, 0, True)
    prop("Description", desc, 0, 0, True)
    prop("LCSC Part", "C6124130", 0, 0, True)
    prop("Manufacturer", "u-blox", 0, 0, True)
    prop("MPN", "ANNA-B402-00B", 0, 0, True)
    prop("ki_keywords", "BLE Bluetooth nRF52833 module u-blox ANNA", 0, 0, True)
    a(f'\t\t(symbol "{name}_0_1"')
    a('\t\t\t(rectangle (start -15.24 38.1) (end 15.24 -38.1)'
      ' (stroke (width 0.254) (type default)) (fill (type background)))')
    a('\t\t)')
    a(f'\t\t(symbol "{name}_1_1"')

    def pin(kind, x, y, ang, nm, num, hide=False):
        h = " (hide yes)" if hide else ""
        a(f'\t\t\t(pin {kind} line (at {f(x)} {f(y)} {ang}) (length 2.54){h}'
          f' (name "{nm}" (effects (font (size 1.27 1.27))))'
          f' (number "{num}" (effects (font (size 1.27 1.27)))))')

    for y, num, nm, kind in LEFT:
        pin(kind, -17.78, y, 0, nm, num)
    for i, (num, nm) in enumerate(GPIO):
        pin("bidirectional", 17.78, 36.83 - i * 2.54, 180, nm, num)
    for i, num in enumerate(GND):
        pin("power_in" if i == 0 else "passive", 0, -40.64, 90, "GND", num, hide=i > 0)
    a('\t\t)')
    a('\t)')
    a(')')
    used = {n for _, n, _, _ in LEFT} | {n for n, _ in GPIO} | set(GND)
    assert used == set(range(1, 57)), sorted(set(range(1, 57)) - used)
    return "\n".join(o) + "\n"


def sexpr_block(text, start):
    """Конец s-выражения, начинающегося с '(' в позиции start (строки учитываются)."""
    depth, i, in_str = 0, start, False
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced s-expression")


def write_symbol(path):
    """Пишет символ в библиотеку; другие символы в файле не трогает."""
    new_lib = symbol()
    if not os.path.exists(path):
        with open(path, "w") as fh:
            fh.write(new_lib)
        return
    s = new_lib.index('\t(symbol "ANNA-B402"')
    new_block = new_lib[s:sexpr_block(new_lib, s + 1)]
    with open(path) as fh:
        text = fh.read()
    key = '(symbol "ANNA-B402"'
    if key in text:
        s = text.index(key)
        text = text[:s] + new_block.lstrip("\t") + text[sexpr_block(text, s):]
    else:
        e = text.rstrip().rindex(")")
        text = text[:e] + new_block + "\n" + text[e:]
    with open(path, "w") as fh:
        fh.write(text)


if __name__ == "__main__":
    pretty = os.path.join(HERE, "cricket.pretty")
    os.makedirs(pretty, exist_ok=True)
    with open(os.path.join(pretty, "ANNA-B402_CornerAntenna.kicad_mod"), "w") as fh:
        fh.write(footprint())
    write_symbol(os.path.join(HERE, "cricket.kicad_sym"))
    print("ok")
