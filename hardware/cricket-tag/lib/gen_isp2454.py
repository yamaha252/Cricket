#!/usr/bin/env python3
"""Символ и футпринты Insight SiP ISP2454-LX (nRF54L15, 8 × 8 × 1 мм) для библиотеки cricket.

Модуль платы с D-29 вместо ANNA-B402 (сравнение — docs/module-options.md).

Источники:
- площадки — библиотека Eagle производителя ISP2454_LX_Eagle_Library.zip,
  корпус ISP2454: 48 площадок 0,4 × 0,4 мм с шагом 0,65 мм (зазор 0,25 мм),
  4 угловые 0,8 × 0,8 мм (GND 1, 7, 25, 31) и 14 механических в антенной
  половине (49–62). Чертёж datasheet R7 (разд. 4.1) даёт чуть другие размеры:
  наружные 0,4 × 0,35 мм, угловые 0,75 × 0,75 и 0,8 × 0,75 мм, центры угловых
  и нижних механических сдвинуты на 0,025 мм. Разница в пределах 0,05 мм,
  футпринт оставлен по библиотеке Eagle;
- зона антенны — datasheet isp_ble_DS2454 R7, раздел 4.3: модуль в 1 мм от
  торцевой кромки; под антенной половиной модуля (4 мм) и до кромки — без меди
  на всех слоях, кроме механических площадок; в углу платы боковая зона 5 мм
  внутрь платы и 1 мм до боковой кромки; на узкой плате — по 1 мм с обеих сторон.

Координаты — вид сверху, начало в центре модуля, ось Y вниз. Модуль повёрнут
на 180° относительно рисунка datasheet: антенная половина смотрит вверх (−Y),
к торцевой кромке, как противовес у ANNA-B402_CornerAntenna. Вывод 1 — справа
снизу.

- ISP2454-LX_CornerAntenna — модуль в левом углу: левая кромка в 1,3 мм от
  корпуса (datasheet: 1 мм; ещё 0,3 мм — под три дорожки VDD, SWDIO, SWDCLK
  вдоль кромки), зона запрета 5 мм вправо от корпуса.
- ISP2454-LX_NarrowEnd — торец платы шириной 10 мм: кромки в 1 мм от корпуса
  с обеих сторон.

Запуск: python3 gen_isp2454.py. Перезаписывает эти два футпринта и символ ISP2454-LX
в cricket.kicad_sym; другие символы библиотеки не трогает.
"""

import os
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
NS = uuid.UUID("0c5e2454-1a2b-4c3d-8e9f-0c0ffee02454")

BODY = 8.0
H = BODY / 2
EDGE_END = 1.0      # торцевая кромка от корпуса
SIDE_EDGE = 1.3     # боковая кромка от корпуса в углу: datasheet 1 мм, +0,3 мм под VDD и SWD вдоль кромки (D-29)
ANT = 4.0           # антенная половина модуля

# (x, y) по библиотеке Eagle (вид сверху, ось Y вверх, антенна внизу), мм
EAGLE = {
    1: (-3.5, 3.5), 7: (-3.5, 0.4), 25: (3.5, 0.4), 31: (3.5, 3.5),
    52: (-3.5, -3.5), 59: (3.5, -3.5),
    2: (-3.7, 2.6), 4: (-3.7, 1.95), 6: (-3.7, 1.3),
    26: (3.7, 1.3), 28: (3.7, 1.95), 30: (3.7, 2.6),
    3: (-3.05, 2.275), 5: (-3.05, 1.625), 29: (3.05, 2.275), 27: (3.05, 1.625),
    49: (-3.7, -0.55), 50: (-3.7, -1.55), 51: (-3.7, -2.55),
    62: (3.7, -0.55), 61: (3.7, -1.55), 60: (3.7, -2.55),
}
for i in range(9):                       # нижний ряд верхней половины 8…24 и верхний ряд 48…32
    EAGLE[8 + 2 * i] = (-2.6 + 0.65 * i, 0.2)
    EAGLE[48 - 2 * i] = (-2.6 + 0.65 * i, 3.7)
for i in range(8):                       # ряды 9…23 и 47…33
    EAGLE[9 + 2 * i] = (-2.275 + 0.65 * i, 0.85)
    EAGLE[47 - 2 * i] = (-2.275 + 0.65 * i, 3.05)
for i in range(6):                       # механические 53…58
    EAGLE[53 + i] = (-2.5 + 1.0 * i, -3.7)
assert sorted(EAGLE) == list(range(1, 63)), sorted(set(range(1, 63)) - set(EAGLE))

BIG = {1, 7, 25, 31, 52, 59}
# поворот на 180° и переход к оси Y вниз: x → −x, y → y
PADS = {n: (-x, y, 0.8 if n in BIG else 0.4) for n, (x, y) in EAGLE.items()}


def f(v):
    s = f"{round(v, 4):.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def footprint(name, side_left, side_right, descr):
    """side_left / side_right — ширина зоны запрета слева и справа от корпуса, мм."""
    uid = lambda k: str(uuid.uuid5(NS, name + k))  # noqa: E731
    o = []
    a = o.append
    a(f'(footprint "{name}"')
    a('\t(version 20240108)')
    a('\t(generator "cricket_gen_isp2454")')
    a('\t(layer "F.Cu")')
    a(f'\t(descr "{descr}")')
    a('\t(tags "Insight SiP ISP2454 nRF54L15 BLE LGA")')
    a(f'\t(property "Reference" "U**" (at {f(H + 0.8)} 0 90) (layer "F.SilkS") (uuid "{uid("ref")}")'
      ' (effects (font (size 0.8 0.8) (thickness 0.15))))')
    a(f'\t(property "Value" "{name}" (at 0 {f(H + 0.8)} 0) (layer "F.Fab") (uuid "{uid("val")}")'
      ' (effects (font (size 0.8 0.8) (thickness 0.12))))')
    for k in ("Footprint", "Datasheet", "Description"):
        v = "https://www.insightsip.com/fichiers_insightsip/pdf/ble/ISP2454/isp_ble_DS2454.pdf" if k == "Datasheet" else ""
        a(f'\t(property "{k}" "{v}" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{uid(k)}")'
          ' (effects (font (size 1.27 1.27))))')
    a('\t(attr smd)')

    def poly(pts, layer, w, key):
        for i in range(len(pts)):
            p, q = pts[i], pts[(i + 1) % len(pts)]
            a(f'\t(fp_line (start {f(p[0])} {f(p[1])}) (end {f(q[0])} {f(q[1])})'
              f' (stroke (width {w}) (type solid)) (layer "{layer}") (uuid "{uid(key + str(i))}"))')

    # F.Fab: корпус и граница антенной половины
    poly([(-H, -H), (H, -H), (H, H), (-H, H)], "F.Fab", 0.1, "fab")
    a(f'\t(fp_line (start {f(-H)} 0) (end {f(H)} 0) (stroke (width 0.05) (type dash)) (layer "F.Fab")'
      f' (uuid "{uid("fabant")}"))')
    a(f'\t(fp_text user "антенна" (at 0 {f(-H / 2)} 0) (layer "F.Fab") (uuid "{uid("fabtxt")}")'
      ' (effects (font (size 0.6 0.6) (thickness 0.08))))')
    # F.SilkS: контур корпуса со стороны выводов, метка вывода 1
    s = H + 0.11
    a(f'\t(fp_line (start {f(-s)} 0) (end {f(-s)} {f(s)}) (stroke (width 0.12) (type solid)) (layer "F.SilkS") (uuid "{uid("s1")}"))')
    a(f'\t(fp_line (start {f(-s)} {f(s)}) (end {f(s)} {f(s)}) (stroke (width 0.12) (type solid)) (layer "F.SilkS") (uuid "{uid("s2")}"))')
    a(f'\t(fp_line (start {f(s)} {f(s)}) (end {f(s)} 0) (stroke (width 0.12) (type solid)) (layer "F.SilkS") (uuid "{uid("s3")}"))')
    x1, y1, _ = PADS[1]
    a(f'\t(fp_circle (center {f(s + 0.3)} {f(y1)}) (end {f(s + 0.4)} {f(y1)})'
      f' (stroke (width 0.2) (type solid)) (fill solid) (layer "F.SilkS") (uuid "{uid("pin1")}"))')

    # F.CrtYd: корпус + 0,25 мм и зона запрета до торцевой кромки
    c = H + 0.25
    ye = -H - EDGE_END
    crt = [(-H - side_left, ye), (H + side_right, ye), (H + side_right, 0), (c, 0), (c, c), (-c, c),
           (-c, 0), (-H - side_left, 0)]
    poly(crt, "F.CrtYd", 0.05, "crt")

    for n in range(1, 63):
        x, y, sz = PADS[n]
        a(f'\t(pad "{n}" smd rect (at {f(x)} {f(y)}) (size {f(sz)} {f(sz)})'
          f' (layers "F.Cu" "F.Paste" "F.Mask") (uuid "{uid(f"pad{n}")}"))')

    ko = [(-H - side_left, ye), (H + side_right, ye), (H + side_right, 0), (-H - side_left, 0)]
    pts = " ".join(f"(xy {f(x)} {f(y)})" for x, y in ko)
    a(f'\t(zone (net 0) (net_name "") (layers "F.Cu" "B.Cu") (uuid "{uid("ko")}") (name "ISP2454_ANT_KEEPOUT")'
      ' (hatch edge 0.5) (connect_pads (clearance 0)) (min_thickness 0.25) (filled_areas_thickness no)'
      ' (keepout (tracks not_allowed) (vias not_allowed) (pads allowed) (copperpour not_allowed) (footprints allowed))'
      ' (placement (enabled no) (sheetname ""))'
      ' (fill (thermal_gap 0.5) (thermal_bridge_width 0.5))'
      f' (polygon (pts {pts})))')
    a(')')
    return "\n".join(o) + "\n"


# ------------------------------------------------------------------ символ
# Назначение площадок — datasheet isp_ble_DS2454 R7, раздел 3 (вариант LX).
GPIO = [  # (номер, имя) по портам, правая сторона
    (29, "P0.00"), (27, "P0.01"), (32, "P0.02"), (34, "P0.03"), (33, "P0.04"),
    (2, "P1.02/NFC1"), (4, "P1.03/NFC2"), (40, "P1.04/AIN0"), (38, "P1.05/AIN1"), (35, "P1.06/AIN2"),
    (36, "P1.07/AIN3"), (19, "P1.08"), (39, "P1.09"), (10, "P1.10"), (48, "P1.11/AIN4"),
    (43, "P1.12/AIN5"), (41, "P1.13/AIN6"), (45, "P1.14/AIN7"), (17, "P1.15"),
    (47, "P2.00"), (6, "P2.01"), (46, "P2.02"), (3, "P2.03"), (44, "P2.04"), (42, "P2.05"),
    (15, "P2.06/TRACECLK"), (11, "P2.07/TRACEDATA0"), (9, "P2.08/TRACEDATA1"), (37, "P2.09/TRACEDATA2"),
    (5, "P2.10/TRACEDATA3"),
]
LEFT = [  # (y, номер, имя, тип)
    (35.56, 26, "VDD_nRF", "power_in"),
    (30.48, 13, "~{RESET}", "input"),
    (25.4, 28, "SWDIO", "bidirectional"),
    (22.86, 30, "SWDCLK", "input"),
    (15.24, 22, "OUT_MOD", "passive"),
    (12.7, 20, "OUT_ANT", "passive"),
]
GND = [1, 7, 8, 12, 14, 16, 18, 21, 23, 24, 25, 31]
MECH = list(range(49, 63))   # механические площадки, ни с чем не соединяются


def symbol():
    name = "ISP2454-LX"
    desc = ("Insight SiP ISP2454-LX, nRF54L15, BLE 6.0 + Coded PHY, встроенная антенна, кварцы 32 МГц "
            "и 32,768 кГц, DC/DC и развязка внутри, LGA-62 8x8 мм. OUT_ANT соединить с OUT_MOD. "
            "P2 без прерываний и пробуждения; АЦП только на P1 (AIN).")
    o = []
    a = o.append

    def prop(k, v, x, y, hide=False):
        h = " (hide yes)" if hide else ""
        a(f'\t\t(property "{k}" "{v}" (at {f(x)} {f(y)} 0){h}'
          f' (effects (font (size 1.27 1.27)){" (justify left)" if not hide else ""}))')

    top = 40.64
    bot = -40.64
    a('(kicad_symbol_lib')
    a('\t(version 20231120)')
    a('\t(generator "cricket_gen_isp2454")')
    a('\t(generator_version "1.0")')
    a(f'\t(symbol "{name}" (exclude_from_sim no) (in_bom yes) (on_board yes)')
    prop("Reference", "U", -15.24, top + 5.08)
    prop("Value", name, -15.24, top + 2.54)
    prop("Footprint", "cricket:ISP2454-LX_CornerAntenna", 0, 0, True)
    prop("Datasheet", "https://www.insightsip.com/fichiers_insightsip/pdf/ble/ISP2454/isp_ble_DS2454.pdf", 0, 0, True)
    prop("Description", desc, 0, 0, True)
    prop("LCSC Part", "C44975104", 0, 0, True)
    prop("Manufacturer", "Insight SiP", 0, 0, True)
    prop("MPN", "ISP2454-LX-RS", 0, 0, True)
    prop("ki_keywords", "BLE Bluetooth nRF54L15 module Insight SiP ISP2454", 0, 0, True)
    a(f'\t\t(symbol "{name}_0_1"')
    a(f'\t\t\t(rectangle (start -15.24 {f(top)}) (end 15.24 {f(bot)})'
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
        pin("bidirectional", 17.78, 38.1 - i * 2.54, 180, nm, num)
    # GND — каждая площадка своим выводом снизу: внутренние центральные (12–18) на двух слоях
    # не вывести, на схеме они помечаются «не подключено» (datasheet разд. 4.2 допускает
    # только наружные площадки)
    for i, num in enumerate(GND):
        pin("passive", -13.97 + i * 2.54, bot - 2.54, 90, "GND", num)
    for num in MECH:
        pin("no_connect", 0, bot, 90, "NC", num, hide=True)
    a('\t\t)')
    a('\t)')
    a(')')
    used = {n for _, n, _, _ in LEFT} | {n for n, _ in GPIO} | set(GND) | set(MECH)
    assert used == set(range(1, 63)), sorted(set(range(1, 63)) - used)
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    import sys
    sys.path.insert(0, HERE)
    from symlib import upsert_symbol
    upsert_symbol(os.path.join(HERE, "cricket.kicad_sym"), "ISP2454-LX", symbol())
    pretty = os.path.join(HERE, "cricket.pretty")
    variants = [
        ("ISP2454-LX_CornerAntenna", SIDE_EDGE, 5.0,
         "Insight SiP ISP2454-LX LGA-62 8x8 мм, nRF54L15, встроенная антенна, модуль в левом углу платы "
         "в 1,3 мм от боковой кромки: зона без меди по isp_ble_DS2454 R7 разд. 4.3"),
        ("ISP2454-LX_NarrowEnd", 1.0, 1.0,
         "Insight SiP ISP2454-LX LGA-62 8x8 мм, nRF54L15, встроенная антенна, торец платы 10 мм: "
         "зона без меди по isp_ble_DS2454 R7 разд. 4.3"),
    ]
    for name, sl, sr, descr in variants:
        with open(os.path.join(pretty, name + ".kicad_mod"), "w") as fh:
            fh.write(footprint(name, sl, sr, descr))
    print("ok")
