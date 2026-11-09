#!/usr/bin/env python3
"""Простые футпринты библиотеки cricket, которых нет в библиотеках KiCad.

- Diodes_W-QFN2020-12 (PAM8904EGPR): Diodes DS41667 Rev. 4-2, «Suggested Pad
  Layout (3) W-QFN2020-12 (Type US)»: площадки 0,25 × 0,5 мм, шаг 0,4 мм,
  внешний размер 2,3 мм, центральная площадка 1,0 × 1,0 мм.
- SameSky_CPT-1117-83-SMT: Same Sky CPT-1117-83-SMT-TR, «Recommended PCB
  Layout»: две площадки 2,5 × 2,5 мм, между ними 10,5 мм; корпус 11 × 9 мм,
  с лепестками 15 мм. Оставлен в библиотеке после D-25.
- SameSky_CPT-9019A-SMT: Same Sky CPT-9019A-SMT-TR, «Recommended PCB Layout»:
  две площадки 1,3 × 3,4 мм, внешний размер 10,0 мм, между ними 7,4 мм;
  корпус 9 × 9 × 1,9 мм. Выбран в D-25.
- WirePads_1x04_P2.0mm, WirePads_1x02_P2.0mm: площадки 1,2 × 2,0 мм с шагом
  2,0 мм под ручную пайку проводов полётника и аккумулятора (D-26). Ставятся на
  нижнюю сторону, без пасты, в BOM и CPL не попадают.
- SWD_Pads_1x04_P2.54mm: четыре круглые площадки 1,2 мм с шагом 2,54 мм под
  подпружиненные контакты или временные провода (D-26). Нижняя сторона, без пасты.

Запуск: python3 gen_footprints.py. Перезаписывает только эти файлы.
"""

import os
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
NS = uuid.UUID("3d1e6a52-77c0-4c8e-b3f1-9a2f0c0ffee4")


def f(v):
    s = f"{round(v, 4):.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class Fp:
    def __init__(self, name, descr, tags):
        self.name = name
        self.o = [f'(footprint "{name}"', '\t(version 20240108)', '\t(generator "cricket_gen_footprints")',
                  '\t(layer "F.Cu")', f'\t(descr "{descr}")', f'\t(tags "{tags}")']

    def uid(self, key):
        return str(uuid.uuid5(NS, self.name + key))

    def props(self, ref_y, val_y, attr="smd"):
        self.o.append(f'\t(property "Reference" "REF**" (at 0 {f(ref_y)} 0) (layer "F.SilkS")'
                      f' (uuid "{self.uid("ref")}") (effects (font (size 0.8 0.8) (thickness 0.12))))')
        self.o.append(f'\t(property "Value" "{self.name}" (at 0 {f(val_y)} 0) (layer "F.Fab")'
                      f' (uuid "{self.uid("val")}") (effects (font (size 0.8 0.8) (thickness 0.12))))')
        for k in ("Footprint", "Datasheet", "Description"):
            self.o.append(f'\t(property "{k}" "" (at 0 0 0) (layer "F.Fab") (hide yes)'
                          f' (uuid "{self.uid(k)}") (effects (font (size 1.27 1.27))))')
        self.o.append(f'\t(attr {attr})')

    def line(self, a, b, layer, w):
        self.o.append(f'\t(fp_line (start {f(a[0])} {f(a[1])}) (end {f(b[0])} {f(b[1])})'
                      f' (stroke (width {w}) (type solid)) (layer "{layer}") (uuid "{self.uid(str(a) + str(b) + layer)}"))')

    def rect(self, x0, y0, x1, y1, layer, w):
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        for i in range(4):
            self.line(pts[i], pts[(i + 1) % 4], layer, w)

    def pad(self, num, x, y, w, h, extra="", shape="rect", layers='"F.Cu" "F.Paste" "F.Mask"'):
        self.o.append(f'\t(pad "{num}" smd {shape} (at {f(x)} {f(y)}) (size {f(w)} {f(h)})'
                      f' (layers {layers}){extra} (uuid "{self.uid("pad" + str(num) + str(x) + str(y))}"))')

    def text_ref_fab(self):
        self.o.append(f'\t(fp_text user "${{REFERENCE}}" (at 0 0 0) (layer "F.Fab") (uuid "{self.uid("fabref")}")'
                      ' (effects (font (size 0.5 0.5) (thickness 0.08))))')

    def write(self):
        self.o.append(")")
        path = os.path.join(HERE, "cricket.pretty", self.name + ".kicad_mod")
        with open(path, "w") as fh:
            fh.write("\n".join(self.o) + "\n")


def wqfn2020_12():
    fp = Fp("Diodes_W-QFN2020-12_2x2mm_P0.4mm_EP1.0x1.0mm",
            "Diodes W-QFN2020-12 (Type US), PAM8904EGPR; DS41667 Rev. 4-2 Suggested Pad Layout",
            "QFN 0.4 Diodes PAM8904E")
    fp.props(-1.9, 1.9)
    c, pl, pw = 0.9, 0.5, 0.25   # центр площадки от оси, длина, ширина
    # 1–3 слева сверху вниз, 4–6 снизу слева направо, 7–9 справа снизу вверх, 10–12 сверху справа налево
    for i, t in enumerate((-0.4, 0, 0.4)):
        fp.pad(1 + i, -c, t, pl, pw)
        fp.pad(4 + i, t, c, pw, pl)
        fp.pad(7 + i, c, -t, pl, pw)
        fp.pad(10 + i, -t, -c, pw, pl)
    # Центральная площадка на GND, паста ~64 %
    fp.pad(13, 0, 0, 1.0, 1.0, " (solder_paste_margin -0.1)")
    fp.rect(-1, -1, 1, 1, "F.Fab", 0.1)
    fp.line((-1.3, -1.3), (-1.3, -0.8), "F.SilkS", 0.12)
    fp.line((-1.3, -1.3), (-0.8, -1.3), "F.SilkS", 0.12)
    for sx, sy in ((1, -1), (1, 1), (-1, 1)):
        fp.line((1.1 * sx, 1.1 * sy), (0.75 * sx, 1.1 * sy), "F.SilkS", 0.12)
        fp.line((1.1 * sx, 1.1 * sy), (1.1 * sx, 0.75 * sy), "F.SilkS", 0.12)
    fp.rect(-1.4, -1.4, 1.4, 1.4, "F.CrtYd", 0.05)
    fp.text_ref_fab()
    fp.write()


def cpt1117():
    fp = Fp("SameSky_CPT-1117-83-SMT",
            "Same Sky CPT-1117-83-SMT-TR piezo transducer 11x9x1.7 mm, tabs 15 mm; Recommended PCB Layout",
            "piezo buzzer transducer Same Sky CUI")
    fp.props(-9, 0)
    fp.pad(1, 0, -6.5, 2.5, 2.5)
    fp.pad(2, 0, 6.5, 2.5, 2.5)
    fp.rect(-4.5, -5.5, 4.5, 5.5, "F.Fab", 0.1)
    fp.rect(-1, -7.5, 1, -5.5, "F.Fab", 0.1)
    fp.rect(-1, 5.5, 1, 7.5, "F.Fab", 0.1)
    s = 0.11
    for sy in (-1, 1):
        fp.line((-4.5 - s, sy * (5.5 + s)), (-1.5, sy * (5.5 + s)), "F.SilkS", 0.12)
        fp.line((1.5, sy * (5.5 + s)), (4.5 + s, sy * (5.5 + s)), "F.SilkS", 0.12)
    fp.line((-4.5 - s, -5.5 - s), (-4.5 - s, 5.5 + s), "F.SilkS", 0.12)
    fp.line((4.5 + s, -5.5 - s), (4.5 + s, 5.5 + s), "F.SilkS", 0.12)
    fp.rect(-4.75, -8.0, 4.75, 8.0, "F.CrtYd", 0.05)
    fp.text_ref_fab()
    fp.write()


def cpt9019a():
    fp = Fp("SameSky_CPT-9019A-SMT",
            "Same Sky CPT-9019A-SMT-TR piezo transducer 9x9x1.9 mm; Recommended PCB Layout",
            "piezo buzzer transducer Same Sky CUI")
    fp.props(-5.6, 0)
    fp.pad(1, -4.35, 0, 1.3, 3.4)
    fp.pad(2, 4.35, 0, 1.3, 3.4)
    fp.rect(-4.5, -4.5, 4.5, 4.5, "F.Fab", 0.1)
    s = 4.61
    for sx in (-1, 1):  # боковые стороны прерываются у площадок
        fp.line((sx * s, -s), (sx * s, -1.95), "F.SilkS", 0.12)
        fp.line((sx * s, 1.95), (sx * s, s), "F.SilkS", 0.12)
    fp.line((-s, -s), (s, -s), "F.SilkS", 0.12)
    fp.line((-s, s), (s, s), "F.SilkS", 0.12)
    fp.rect(-5.25, -4.85, 5.25, 4.85, "F.CrtYd", 0.05)
    fp.text_ref_fab()
    fp.write()


NO_ASSEMBLY = "smd exclude_from_pos_files exclude_from_bom"
COPPER_ONLY = '"F.Cu" "F.Mask"'


def wire_pads(n, pitch=2.0):
    fp = Fp(f"WirePads_1x{n:02d}_P2.0mm",
            f"{n} solder pads 1.2x2.0 mm, pitch 2.0 mm, for hand-soldered wires; no paste, not assembled",
            "wire solder pad")
    fp.props(-2.0, 2.0, NO_ASSEMBLY)
    x0 = -(n - 1) * pitch / 2
    for i in range(n):
        fp.pad(i + 1, x0 + i * pitch, 0, 1.2, 2.0, layers=COPPER_ONLY)
    # метка первого вывода
    fp.line((x0 - 0.85, -1.3), (x0 - 0.85, 1.3), "F.SilkS", 0.12)
    fp.rect(x0 - 0.85, -1.25, -x0 + 0.85, 1.25, "F.CrtYd", 0.05)
    fp.text_ref_fab()
    fp.write()


def swd_pads(pitch=2.54):
    fp = Fp("SWD_Pads_1x04_P2.54mm",
            "SWD test pads: VDD, SWDIO, SWCLK, GND; round 1.2 mm, pitch 2.54 mm; no paste, not assembled",
            "SWD test pad pogo")
    fp.props(-1.6, 1.6, NO_ASSEMBLY)
    x0 = -1.5 * pitch
    for i in range(4):
        fp.pad(i + 1, x0 + i * pitch, 0, 1.2, 1.2, shape="circle", layers=COPPER_ONLY)
    fp.line((x0 - 0.9, -0.9), (x0 - 0.9, 0.9), "F.SilkS", 0.12)
    fp.rect(x0 - 0.85, -0.85, -x0 + 0.85, 0.85, "F.CrtYd", 0.05)
    fp.text_ref_fab()
    fp.write()


if __name__ == "__main__":
    wqfn2020_12()
    cpt1117()
    cpt9019a()
    wire_pads(4)
    wire_pads(2)
    swd_pads()
    print("ok")
