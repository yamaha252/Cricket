#!/usr/bin/env python3
"""Простые символы библиотеки cricket, которых нет в библиотеках KiCad.

- TP4054: зарядка Li-Ion, SOT-23-5. Выводы как у TOPPOWER TP4054-42-SOT25R
  (C32574) и исходной LTC4054: 1 CHRG, 2 GND, 3 BAT, 4 VCC, 5 PROG.
- TPS7A0233: LDO 3,3 В, корпус DBV (SOT-23-5). TI SBVS277, табл. 5-1:
  1 IN, 2 GND, 3 EN, 4 NC, 5 OUT.
- PAM8904E: драйвер пьезоизлучателя, W-QFN2020-12. Diodes DS41667 Rev. 4-2:
  1 EN1, 2 EN2, 3 DIN, 4 CN1, 5 GND, 6 VO2, 7 VO1, 8 CN2, 9 CP1, 10 VOUT,
  11 CP2, 12 VIN; 13 — центральная площадка, на GND.
- VBAT: символ питания для цепи аккумулятора.

Запуск: python3 gen_symbols.py. Перезаписывает только эти символы в
cricket.kicad_sym.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from symlib import upsert_symbol  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

HEAD = ('(kicad_symbol_lib\n\t(version 20231120)\n\t(generator "cricket_gen_symbols")\n'
        '\t(generator_version "1.0")\n')


def prop(k, v, x=0, y=0, hide=True, justify=None):
    h = " (hide yes)" if hide else ""
    j = f" (justify {justify})" if justify else ""
    return (f'\t\t(property "{k}" "{v}" (at {x} {y} 0){h}'
            f' (effects (font (size 1.27 1.27)){j}))\n')


def pin(kind, x, y, ang, name, num, length=2.54, hide=False):
    h = " (hide yes)" if hide else ""
    return (f'\t\t\t(pin {kind} line (at {x} {y} {ang}) (length {length}){h}'
            f' (name "{name}" (effects (font (size 1.27 1.27))))'
            f' (number "{num}" (effects (font (size 1.27 1.27)))))\n')


def ic(name, value, desc, fp, ds, lcsc, mpn, maker, keywords, left, right, gnd, gnd_extra=()):
    """Прямоугольный символ 15,24 мм шириной: left/right — [(y, тип, имя, номер)]."""
    w = 7.62
    ys = [p[0] for p in left + right]
    top, bot = max(ys) + 2.54, min(ys) - 2.54
    s = f'\t(symbol "{name}" (exclude_from_sim no) (in_bom yes) (on_board yes)\n'
    s += prop("Reference", "U", -w, top + 1.27, hide=False, justify="left")
    s += prop("Value", value, -w, bot - 3.81, hide=False, justify="left")
    s += prop("Footprint", fp)
    s += prop("Datasheet", ds)
    s += prop("Description", desc)
    s += prop("LCSC Part", lcsc)
    s += prop("Manufacturer", maker)
    s += prop("MPN", mpn)
    s += prop("ki_keywords", keywords)
    s += f'\t\t(symbol "{name}_0_1"\n'
    s += (f'\t\t\t(rectangle (start {-w} {top}) (end {w} {bot})'
          ' (stroke (width 0.254) (type default)) (fill (type background)))\n')
    s += '\t\t)\n'
    s += f'\t\t(symbol "{name}_1_1"\n'
    for y, kind, nm, num in left:
        s += pin(kind, -w - 2.54, y, 0, nm, num)
    for y, kind, nm, num in right:
        s += pin(kind, w + 2.54, y, 180, nm, num)
    s += pin("power_in", 0, bot - 2.54, 90, "GND", gnd)
    for num in gnd_extra:  # в той же точке, скрыты
        s += pin("passive", 0, bot - 2.54, 90, "GND", num, hide=True)
    s += '\t\t)\n\t)\n'
    return s


def tp4054():
    return ic(
        "TP4054", "TP4054-42-SOT25R",
        "Зарядка Li-Ion 4,2 В, линейная, до 500 мА, SOT-23-5. Ток заряда 1000 В / R_PROG. "
        "CHRG — открытый сток, низкий уровень во время заряда.",
        "Package_TO_SOT_SMD:SOT-23-5", "https://www.lcsc.com/product-detail/C32574.html",
        "C32574", "TP4054-42-SOT25R", "TOPPOWER", "charger Li-Ion LiPo linear TP4054",
        left=[(2.54, "power_in", "VCC", "4"), (-2.54, "passive", "PROG", "5")],
        right=[(2.54, "passive", "BAT", "3"), (-2.54, "open_collector", "~{CHRG}", "1")],
        gnd="2")


def tps7a0233():
    return ic(
        "TPS7A0233", "TPS7A0233PDBVR",
        "LDO 3,3 В 200 мА, Iq 25 нА, вход до 6 В, SOT-23-5 (DBV). Выход ≥0,5 мкФ эффективной ёмкости.",
        "Package_TO_SOT_SMD:SOT-23-5", "https://www.ti.com/lit/ds/symlink/tps7a02.pdf",
        "C2887324", "TPS7A0233PDBVR", "Texas Instruments", "LDO regulator 3.3V nanopower",
        left=[(2.54, "power_in", "IN", "1"), (-2.54, "input", "EN", "3")],
        right=[(2.54, "power_out", "OUT", "5"), (-2.54, "no_connect", "NC", "4")],
        gnd="2")


def pam8904e():
    return ic(
        "PAM8904E", "PAM8904EGPR",
        "Драйвер пьезоизлучателя с подкачкой заряда 1x/2x/3x, VIN 1,5–5,5 В (3x — до 4,5 В), "
        "W-QFN2020-12. Режим: DIN=0 — выкл.; EN1 EN2: 00 выкл., 01 1x, 10 2x, 11 3x.",
        "cricket:Diodes_W-QFN2020-12_2x2mm_P0.4mm_EP1.0x1.0mm",
        "https://www.diodes.com/assets/Datasheets/PAM8904E.pdf",
        "C510550", "PAM8904EGPR", "Diodes Incorporated", "piezo sounder driver charge pump",
        left=[(7.62, "power_in", "VIN", "12"), (2.54, "input", "EN1", "1"), (0, "input", "EN2", "2"),
              (-2.54, "input", "DIN", "3"), (-7.62, "passive", "CP1", "9"), (-10.16, "passive", "CN1", "4")],
        right=[(7.62, "power_out", "VOUT", "10"), (2.54, "output", "VO1", "7"), (0, "output", "VO2", "6"),
               (-7.62, "passive", "CP2", "11"), (-10.16, "passive", "CN2", "8")],
        gnd="5", gnd_extra=("13",))


def vbat():
    return (
        '\t(symbol "VBAT" (power) (pin_numbers (hide yes)) (pin_names (offset 0) (hide yes))'
        ' (exclude_from_sim no) (in_bom yes) (on_board yes)\n'
        + prop("Reference", "#PWR", 0, -3.81)
        + prop("Value", "VBAT", 0, 3.556, hide=False)
        + prop("Footprint", "")
        + prop("Datasheet", "")
        + prop("Description", 'Power symbol creates a global label with name \\"VBAT\\"')
        + prop("ki_keywords", "global power battery")
        + '\t\t(symbol "VBAT_0_1"\n'
        '\t\t\t(polyline (pts (xy -0.762 1.27) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none)))\n'
        '\t\t\t(polyline (pts (xy 0 2.54) (xy 0.762 1.27)) (stroke (width 0) (type default)) (fill (type none)))\n'
        '\t\t\t(polyline (pts (xy 0 0) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none)))\n'
        '\t\t)\n'
        '\t\t(symbol "VBAT_1_1"\n'
        '\t\t\t(pin power_in line (at 0 0 90) (length 0) (hide yes)'
        ' (name "VBAT" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))\n'
        '\t\t)\n\t)\n')


if __name__ == "__main__":
    path = os.path.join(HERE, "cricket.kicad_sym")
    for name, fn in (("TP4054", tp4054), ("TPS7A0233", tps7a0233), ("PAM8904E", pam8904e), ("VBAT", vbat)):
        upsert_symbol(path, name, HEAD + fn() + ")\n")
    print("ok")
