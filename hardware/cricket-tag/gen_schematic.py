#!/usr/bin/env python3
"""Генератор схемы cricket-tag (ревизия A).

Схема собирается этим скриптом по шагам из README.md. Каждый вывод
подключается коротким проводом к метке цепи или к символу питания, поэтому
связи задаются списком цепей, а не трассировкой проводов. Пока схема
строится скриптом, исправлять нужно его, а не cricket-tag.kicad_sch:
ручные правки пропадут при следующем запуске. Когда схема будет готова и её
начнут править в KiCad, скрипт перестаёт быть источником.

Запуск: python3 gen_schematic.py  (затем ERC, см. CLAUDE.md).
"""

import math
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
from symlib import find_symbol_text, parse, sexpr_end, unq  # noqa: E402

KICAD_SYM = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
LIBS = {
    "Device": f"{KICAD_SYM}/Device.kicad_sym",
    "Connector_Generic": f"{KICAD_SYM}/Connector_Generic.kicad_sym",
    "Connector": f"{KICAD_SYM}/Connector.kicad_sym",
    "power": f"{KICAD_SYM}/power.kicad_sym",
    "Switch": f"{KICAD_SYM}/Switch.kicad_sym",
    "Transistor_FET": f"{KICAD_SYM}/Transistor_FET.kicad_sym",
    "Sensor_Motion": f"{KICAD_SYM}/Sensor_Motion.kicad_sym",
    "cricket": os.path.join(HERE, "lib", "cricket.kicad_sym"),
}
ROOT_UUID = "56dee62f-8129-4e4a-ba8f-7a3ded8abe6b"
PROJECT = "cricket-tag"
NS = uuid.UUID("0b5e2c4a-1f7d-4c39-8e0a-c41c4e7a9a01")
G = 2.54  # шаг сетки, мм
X0, Y0 = 4, 2  # отступ всего содержимого от рамки листа, клеток

POWER_NETS = {"GND": "power:GND", "+5V": "power:+5V", "+3V3": "power:+3V3", "VBAT": "cricket:VBAT"}

_lib_cache = {}


def uid(key):
    return str(uuid.uuid5(NS, key))


def f(v):
    s = f"{round(v, 4):.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def flatten(lib_text, text, name, parent):
    """Производный символ → самостоятельный: графика и выводы родителя
    с именем потомка, свойства потомка. Так KiCad хранит их в схеме."""
    ptext = find_symbol_text(lib_text, parent)
    blocks, pos = [], 0
    key = f'(symbol "{parent}_'
    while True:
        i = ptext.find(key, pos)
        if i < 0:
            break
        e = sexpr_end(ptext, i)
        blocks.append(ptext[i:e].replace(f'(symbol "{parent}_', f'(symbol "{name}_', 1))
        pos = e
    s = text.find("(extends")
    text = text[:s] + text[sexpr_end(text, s):]
    # Заголовок родителя (pin_names, in_bom, exclude_from_sim…) наследуется, если у потомка его нет
    text = _merge_header(ptext, text)
    end = text.rstrip().rindex(")")
    return text[:end] + "\n\t\t" + "\n\t\t".join(blocks) + "\n\t" + text[end:]


def _header_items(text):
    """Элементы символа до первого (property: [(ключ, текст)], начало и конец области."""
    start = text.index("\n") + 1
    stop = text.index("(property")
    items, pos = [], start
    while True:
        i = text.find("(", pos, stop)
        if i < 0:
            break
        e = sexpr_end(text, i)
        items.append((text[i + 1:e].split(None, 1)[0], text[i:e]))
        pos = e
    return items, start, stop


def _merge_header(parent, child):
    p_items, _, _ = _header_items(parent)
    c_items, start, stop = _header_items(child)
    own = dict(c_items)
    keys = [k for k, _ in p_items] + [k for k, _ in c_items if k not in dict(p_items)]
    merged = [own.get(k) or dict(p_items)[k] for k in keys]
    return child[:start] + "".join("\t\t" + m + "\n" for m in merged) + "\t\t" + child[stop:]


def lib_symbol(lib_id):
    """(текст символа, {номер: (x, y, угол)}) из библиотеки."""
    if lib_id not in _lib_cache:
        lib, name = lib_id.split(":")
        with open(LIBS[lib]) as fh:
            lib_text = fh.read()
        text = find_symbol_text(lib_text, name)
        tree = parse(text)
        ext = next((t for t in tree if isinstance(t, list) and t and t[0] == "extends"), None)
        if ext:
            text = flatten(lib_text, text, name, unq(ext[1]))
            tree = parse(text)
        pins, props = {}, {}
        for t in tree:
            if not isinstance(t, list) or not t:
                continue
            if t[0] == "property":
                at = next(x for x in t if isinstance(x, list) and x[0] == "at")
                props[unq(t[1])] = (float(at[1]), float(at[2]))
            if t[0] == "symbol":
                unit = int(unq(t[1]).rsplit("_", 2)[1])
                if unit not in (0, 1):
                    continue
                for p in t:
                    if isinstance(p, list) and p and p[0] == "pin":
                        at = next(x for x in p if isinstance(x, list) and x[0] == "at")
                        num = next(x for x in p if isinstance(x, list) and x[0] == "number")
                        pins[unq(num[1])] = (float(at[1]), float(at[2]), float(at[3]))
        _lib_cache[lib_id] = (text, pins, props)
    return _lib_cache[lib_id]


def xform(x, y, rot, mirror):
    """Точка символа (Y вверх) → смещение на схеме (Y вниз)."""
    if mirror:
        x = -x
    a = math.radians(rot)
    rx = x * math.cos(a) - y * math.sin(a)
    ry = x * math.sin(a) + y * math.cos(a)
    return rx, -ry


class Part:
    def __init__(self, sch, lib_id, ref, x, y, rot, mirror):
        self.sch, self.lib_id, self.ref = sch, lib_id, ref
        self.x, self.y, self.rot, self.mirror = x, y, rot, mirror
        _, self.pins, self.props = lib_symbol(lib_id)

    def pin(self, num):
        """(x, y) конца вывода и единичный вектор наружу от корпуса."""
        px, py, ang = self.pins[str(num)]
        dx, dy = xform(px, py, self.rot, self.mirror)
        a = math.radians(ang)
        ix, iy = xform(math.cos(a), math.sin(a), self.rot, self.mirror)
        return (self.x + dx, self.y + dy), (-round(ix), -round(iy))


class Schematic:
    def __init__(self):
        self.items = []
        self.used = []
        self.npwr = 0
        self.parts = {}
        self.exclusions = []

    # ---------------------------------------------------------- символы
    def place(self, lib_id, ref, x, y, value, rot=0, mirror=False, footprint="", lcsc="",
              fields=None, ref_at=None, val_at=None, dnp=False, bom=True):
        x, y = (x + X0) * G, (y + Y0) * G
        p = Part(self, lib_id, ref, x, y, rot, mirror)
        if lib_id not in self.used:
            self.used.append(lib_id)
        text, pins, props = lib_symbol(lib_id)
        is_power = ref.startswith("#")

        def at_of(key, default):
            if default is not None:
                return x + default[0] * G, y + default[1] * G
            lx, ly = props.get(key, (0, 0))
            dx, dy = xform(lx, ly, rot, mirror)
            return x + dx, y + dy

        rx, ry = at_of("Reference", ref_at)
        vx, vy = at_of("Value", val_at)
        just = "" if is_power or ref_at is None or ref_at[0] == 0 else (
            " (justify left)" if ref_at[0] > 0 else " (justify right)")
        o = [f'\t(symbol (lib_id "{lib_id}") (at {f(x)} {f(y)} {rot})'
             + (" (mirror y)" if mirror else "")
             + f' (unit 1) (exclude_from_sim no) (in_bom {"no" if is_power or not bom else "yes"})'
             f' (on_board {"no" if is_power else "yes"}) (dnp {"yes" if dnp else "no"})'
             f' (uuid "{uid("sym" + ref)}")']
        hide_ref = " (hide yes)" if is_power else ""
        o.append(f'\t\t(property "Reference" "{ref}" (at {f(rx)} {f(ry)} 0)'
                 f' (effects (font (size 1.27 1.27)){just}){hide_ref})')
        o.append(f'\t\t(property "Value" "{value}" (at {f(vx)} {f(vy)} 0)'
                 f' (effects (font (size 1.27 1.27)){just}))')
        o.append(f'\t\t(property "Footprint" "{footprint}" (at {f(x)} {f(y)} 0)'
                 ' (effects (font (size 1.27 1.27)) (hide yes)))')
        o.append(f'\t\t(property "Datasheet" "" (at {f(x)} {f(y)} 0)'
                 ' (effects (font (size 1.27 1.27)) (hide yes)))')
        extra = dict(fields or {})
        if lcsc:
            extra["LCSC Part"] = lcsc
        for k, v in extra.items():
            o.append(f'\t\t(property "{k}" "{v}" (at {f(x)} {f(y)} 0)'
                     ' (effects (font (size 1.27 1.27)) (hide yes)))')
        for num in pins:
            o.append(f'\t\t(pin "{num}" (uuid "{uid("pin" + ref + num)}"))')
        o.append(f'\t\t(instances (project "{PROJECT}" (path "/{ROOT_UUID}"'
                 f' (reference "{ref}") (unit 1))))')
        o.append('\t)')
        self.items.append("\n".join(o))
        if not is_power:
            self.parts[ref] = p
        return p

    def power(self, net, pt, out=None):
        """Символ питания в точке pt, повёрнутый по направлению провода out."""
        self.npwr += 1
        lib_id = POWER_NETS[net] if net != "PWR_FLAG" else "power:PWR_FLAG"
        ref = f"#PWR{self.npwr:02d}" if net != "PWR_FLAG" else f"#FLG{self.npwr:02d}"
        if net == "GND":   # тело символа снизу
            rot = {(0, 1): 0, (1, 0): 90, (-1, 0): 270, (0, -1): 180}.get(out, 0)
        else:              # тело символа сверху
            rot = {(0, -1): 0, (1, 0): 270, (-1, 0): 90, (0, 1): 180}.get(out, 0)
        self.place(lib_id, ref, pt[0] / G - X0, pt[1] / G - Y0, net, rot=rot)

    # ------------------------------------------------------------ связи
    def wire(self, a, b):
        self.items.append(f'\t(wire (pts (xy {f(a[0])} {f(a[1])}) (xy {f(b[0])} {f(b[1])}))'
                          f' (stroke (width 0) (type default)) (uuid "{uid("w" + str(a) + str(b))}"))')

    def label(self, pt, name, out):
        ang = {(1, 0): 0, (-1, 0): 180}.get(out, 0)
        just = "right" if ang == 180 else "left"
        self.items.append(f'\t(label "{name}" (at {f(pt[0])} {f(pt[1])} {ang})'
                          f' (effects (font (size 1.27 1.27)) (justify {just} bottom))'
                          f' (uuid "{uid("l" + name + str(pt))}"))')

    def junction(self, pt):
        self.items.append(f'\t(junction (at {f(pt[0])} {f(pt[1])}) (diameter 0) (color 0 0 0 0)'
                          f' (uuid "{uid("j" + str(pt))}"))')

    def no_connect(self, part, num):
        (x, y), _ = part.pin(num)
        self.items.append(f'\t(no_connect (at {f(x)} {f(y)}) (uuid "{uid("nc" + part.ref + str(num))}"))')

    def connect(self, part, num, net, stub=1):
        """Провод от вывода наружу и метка или символ питания на конце."""
        (x, y), (ox, oy) = part.pin(num)
        end = (x + ox * stub * G, y + oy * stub * G)
        self.wire((x, y), end)
        if net in POWER_NETS:
            self.power(net, end, (ox, oy))
        else:
            self.label(end, net, (ox, oy))
        return end

    def connect_pins(self, a, na, b, nb, label=None):
        """Провод между концами двух выводов; метка цепи на конце второго."""
        pa, _ = a.pin(na)
        pb, _ = b.pin(nb)
        self.wire(pa, pb)
        if label:
            self.label(pb, label, (1, 0))

    def flag(self, net, x, y):
        """PWR_FLAG на цепи net отдельной парой символов в точке (x, y)."""
        x, y = (x + X0) * G, (y + Y0) * G
        if net == "GND":
            self.power("PWR_FLAG", (x, y), (0, -1))
            self.wire((x, y), (x, y + G))
            self.power("GND", (x, y + G), (0, 1))
        elif net in POWER_NETS:
            self.power(net, (x, y), (0, -1))
            self.wire((x, y), (x, y + G))
            self.power("PWR_FLAG", (x, y + G), (0, 1))
        else:
            self.power("PWR_FLAG", (x, y), (0, -1))
            self.wire((x, y), (x, y + G))
            self.label((x, y + G), net, (1, 0))

    def exclude(self, code, a, na, b, nb, comment):
        """Намеренное замечание ERC между выводами — в исключения проекта.
        Ключ как у KiCad 10: код|x|y|uuid вывода|uuid вывода|путь|путь|путь, x и y в 0,1 мкм."""
        (x, y), _ = a.pin(na)
        path = f"/{ROOT_UUID}/"
        key = (f"{code}|{round(x * 10000)}|{round(y * 10000)}|{uid('pin' + a.ref + str(na))}"
               f"|{uid('pin' + b.ref + str(nb))}|{path}|{path}|{path}")
        self.exclusions.append([key, comment])

    def write_exclusions(self, pro_path):
        import json
        with open(pro_path) as fh:
            pro = json.load(fh)
        pro.setdefault("erc", {})["erc_exclusions"] = self.exclusions
        with open(pro_path, "w") as fh:
            json.dump(pro, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    def text(self, x, y, s, size=1.27):
        s = s.replace('"', '\\"')
        self.items.append(f'\t(text "{s}" (exclude_from_sim no) (at {f((x + X0) * G)} {f((y + Y0) * G)} 0)'
                          f' (effects (font (size {size} {size})) (justify left bottom))'
                          f' (uuid "{uid("t" + s)}"))')

    # ------------------------------------------------------------ вывод
    def write(self, path):
        libs = []
        for lib_id in self.used:
            text = lib_symbol(lib_id)[0]
            name = lib_id.split(":")[1]
            libs.append("\t\t" + text.replace(f'(symbol "{name}"', f'(symbol "{lib_id}"', 1)
                        .replace("\n", "\n\t"))
        out = [
            "(kicad_sch",
            "\t(version 20260306)",
            '\t(generator "cricket_gen_schematic")',
            '\t(generator_version "1.0")',
            f'\t(uuid "{ROOT_UUID}")',
            '\t(paper "A3")',
            "\t(title_block",
            '\t\t(title "Cricket Tag")',
            '\t\t(rev "A")',
            '\t\t(comment 1 "Ultra-light BLE crash beacon, u-blox ANNA-B402 (nRF52833)")',
            "\t)",
            "\t(lib_symbols",
            *libs,
            "\t)",
            *self.items,
            '\t(sheet_instances (path "/" (page "1")))',
            "\t(embedded_fonts no)",
            ")",
        ]
        with open(path, "w") as fh:
            fh.write("\n".join(out) + "\n")


# --------------------------------------------------------------------------
R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
SOT235 = "Package_TO_SOT_SMD:SOT-23-5"


def res(s, ref, x, y, value, lcsc, top, bottom):
    r = s.place("Device:R", ref, x, y, value, footprint=R0402, lcsc=lcsc,
                ref_at=(1, -0.5), val_at=(1, 0.5))
    s.connect(r, 1, top)
    s.connect(r, 2, bottom)
    return r


def cap(s, ref, x, y, value, lcsc, top, bottom="GND", fp=C0402):
    c = s.place("Device:C", ref, x, y, value, footprint=fp, lcsc=lcsc,
                ref_at=(1, -0.5), val_at=(1, 0.5))
    s.connect(c, 1, top)
    s.connect(c, 2, bottom)
    return c


def power_section(s):
    """Шаг 2: вход 5 В, VIN_SENSE, TP4054, аккумулятор, делитель VBAT, LDO."""
    s.text(4, 5, "Питание: 5 В от полётника → Шоттки → TP4054 (45 мА) → Li-Po 1S → TPS7A0233 → +3V3", 1.8)

    # Площадки проводов полётника J1 (снизу, только медь, D-26): 1 — 5 В, 2 — GND, 3 — TX полётника, 4 — RX
    j1 = s.place("Connector_Generic:Conn_01x04", "J1", 6, 12, "FC 5V/GND/TX/RX", mirror=True,
                 footprint="cricket:WirePads_1x04_P2.0mm", ref_at=(0, -3), val_at=(0, 4), bom=False)
    a, _ = j1.pin(1)
    s.wire(a, (a[0] + 2 * G, a[1]))
    s.power("+5V", (a[0] + 2 * G, a[1]), (0, -1))
    s.connect(j1, 2, "GND", stub=6)
    s.connect(j1, 3, "FC_TX", stub=2)
    s.connect(j1, 4, "FC_RX", stub=2)
    s.text(3, 19, "FC_TX, FC_RX — через R6, R7\\nпо 1 кОм к UART модуля")

    # Шоттки: аккумулятор не питает полётник через TP4054
    d1 = s.place("Device:D_Schottky", "D1", 28, 10, "B5819W", rot=180,
                 footprint="Diode_SMD:D_SOD-123", lcsc="C8598", ref_at=(0, -2), val_at=(0, 2))
    s.connect(d1, 2, "+5V")
    s.connect(d1, 1, "VCHG")

    # Делитель VIN_SENSE: 1 МОм / 1,5 МОм → 2,85–3,15 В на GPIO при 5 В ±5 % (D-23)
    r1 = s.place("Device:R", "R1", 24, 17, "1MΩ", footprint=R0402, lcsc="C26083",
                 ref_at=(1, -0.5), val_at=(1, 0.5))
    r2 = s.place("Device:R", "R2", 24, 22, "1,5MΩ", footprint=R0402, lcsc="C22276",
                 ref_at=(1, -0.5), val_at=(1, 0.5))
    s.connect(r1, 1, "+5V")
    s.connect_pins(r1, 2, r2, 1, "VIN_SENSE")
    s.connect(r2, 2, "GND")

    # TP4054: ток заряда 1000 В / 22 кОм ≈ 45 мА
    cap(s, "C1", 34, 17, "10µF 10V", "C19702", "VCHG", fp=C0603)
    u2 = s.place("cricket:TP4054", "U2", 50, 17, "TP4054-42-SOT25R", footprint=SOT235, lcsc="C32574",
                 fields={"MPN": "TP4054-42-SOT25R"})
    s.connect(u2, 4, "VCHG", stub=2)
    s.connect(u2, 2, "GND")
    s.connect(u2, 3, "VBAT", stub=2)
    s.connect(u2, 1, "CHRG_N", stub=2)
    s.connect(u2, 5, "PROG", stub=2)
    res(s, "R3", 40, 23, "22kΩ", "C25768", "PROG", "GND")
    cap(s, "C2", 64, 17, "1µF 25V", "C52923", "VBAT")
    s.text(56, 23, "~{CHRG}: открытый сток,\\nподтяжка внутри nRF")

    # Площадки проводов аккумулятора J2 (снизу, только медь, D-26): 1 — плюс, 2 — минус
    j2 = s.place("Connector_Generic:Conn_01x02", "J2", 6, 33, "LiPo 1S", mirror=True,
                 footprint="cricket:WirePads_1x02_P2.0mm", ref_at=(0, -2), val_at=(0, 3), bom=False)
    a, _ = j2.pin(1)
    s.wire(a, (a[0] + 2 * G, a[1]))
    s.power("VBAT", (a[0] + 2 * G, a[1]), (0, -1))
    s.connect(j2, 2, "GND", stub=4)
    s.text(3, 39, "J1, J2 — площадки под пайку\\nпроводов снизу, без деталей.\\nJ2: 1 — плюс, 2 — минус")

    # Делитель VBAT: 1 МОм / 1 МОм + 100 нФ, VBAT/2 ≤ 2,1 В на АЦП
    r4 = s.place("Device:R", "R4", 24, 32, "1MΩ", footprint=R0402, lcsc="C26083",
                 ref_at=(1, -0.5), val_at=(1, 0.5))
    r5 = s.place("Device:R", "R5", 24, 37, "1MΩ", footprint=R0402, lcsc="C26083",
                 ref_at=(1, -0.5), val_at=(1, 0.5))
    s.connect(r4, 1, "VBAT")
    s.connect_pins(r4, 2, r5, 1, "VBAT_SENSE")
    s.connect(r5, 2, "GND")
    cap(s, "C3", 32, 37, "100nF", "C1525", "VBAT_SENSE")

    # LDO 3,3 В, EN на VBAT: включён всегда
    cap(s, "C4", 42, 35, "1µF 25V", "C52923", "VBAT")
    u3 = s.place("cricket:TPS7A0233", "U3", 54, 35, "TPS7A0233PDBVR", footprint=SOT235, lcsc="C2887324",
                 fields={"MPN": "TPS7A0233PDBVR"})
    s.connect_pins(u3, 3, u3, 1)
    s.connect(u3, 1, "VBAT", stub=2)
    s.connect(u3, 2, "GND")
    s.connect(u3, 5, "+3V3", stub=2)
    cap(s, "C5", 66, 35, "1µF 25V", "C52923", "+3V3")

    # Флаги источников для ERC: 5 В и земля приходят с разъёма, VBAT — аккумулятор
    s.text(74, 9, "Флаги ERC")
    for i, net in enumerate(("+5V", "VCHG", "VBAT", "GND")):
        s.flag(net, 75 + 4 * i, 12)


# Назначение выводов ANNA-B402 (номер площадки → цепь). Только наружный ряд
# площадок и верхний ряд 40–42: внутренние ряды на 2 слоях без via не вывести.
# Выводы «low-frequency only» (19, 20, 27–30) — только медленные сигналы.
GPIO_MAP = {
    14: "UART_TX",     # P0.11 → RX полётника через 1 кОм
    15: "UART_RX",     # P0.12 ← TX полётника через 1 кОм
    16: "BUZ_DIN",     # P1.00 (SWO) — ШИМ 4 кГц на PAM8904E
    19: "VBAT_SENSE",  # P0.03/AIN1, LF
    20: "VIN_SENSE",   # P0.02/AIN0, LF — есть ли 5 В, будит из System OFF
    27: "LED",         # P0.31, LF — затвор 2N7002
    28: "CHRG_N",      # P0.30, LF — открытый сток TP4054, внутренняя подтяжка
    29: "BUTTON",      # P0.29, LF — кнопка на GND, внутренняя подтяжка
    30: "ACC_INT1",    # P0.28, LF — прерывание LIS2DH12
    31: "BUZ_EN1",     # P0.27 — режим PAM8904E
    32: "I2C_SCL",     # P0.06
    33: "I2C_SDA",     # P0.26
    40: "BUZ_EN2",     # P0.15 — режим PAM8904E
}


def module_section(s):
    """Шаг 3: ANNA-B402, кварц 32,768 кГц, развязка, площадки SWD."""
    s.text(84, 45, "Модуль: u-blox ANNA-B402 (nRF52833), кварц 32,768 кГц, SWD", 1.8)
    u1 = s.place("cricket:ANNA-B402", "U1", 120, 64, "ANNA-B402-00B",
                 footprint="cricket:ANNA-B402_CornerAntenna", lcsc="C6124130",
                 fields={"MPN": "ANNA-B402-00B", "Manufacturer": "u-blox"})
    s.connect(u1, 9, "+3V3", stub=2)
    s.connect(u1, 42, "SWDIO", stub=2)
    s.connect(u1, 41, "SWDCLK", stub=2)
    s.connect(u1, 17, "XL1", stub=2)
    s.connect(u1, 18, "XL2", stub=2)
    # Встроенная антенна: ANT ↔ ANT_INT, ANT_PCB — к противовесу в футпринте
    s.connect_pins(u1, 6, u1, 5)
    for n in (1, 2, 3, 12, 21, 34, 35):
        s.no_connect(u1, n)
    s.text(91, 85, "ANT ↔ ANT_INT перемычкой; ANT_PCB (1) — противовес\\nв футпринте; ANT_GND1/2 при установке в углу\\nне подключаются. USB, VBUS, ~{RESET} не используются.")
    gpio = [int(n) for n in u1.pins if n not in ("9", "21", "12", "42", "41", "16", "17", "18",
                                                 "6", "5", "1", "2", "3", "34", "35")
            and u1.pins[n][0] > 0]
    for n in [16] + gpio:
        if n in GPIO_MAP:
            s.connect(u1, n, GPIO_MAP[n], stub=2)
        else:
            s.no_connect(u1, n)
    s.connect(u1, 4, "GND")

    # Развязка VCC модуля
    cap(s, "C6", 100, 53, "100nF", "C1525", "+3V3")
    cap(s, "C7", 104, 53, "1µF 25V", "C52923", "+3V3")

    # Кварц 32,768 кГц (D-16): CL 12,5 пФ → 2 × 18 пФ
    y1 = s.place("Device:Crystal", "Y1", 96, 66, "32,768kHz",
                 footprint="Crystal:Crystal_SMD_2012-2Pin_2.0x1.2mm", lcsc="C55208",
                 fields={"MPN": "X1A0000610002", "Manufacturer": "Seiko Epson"},
                 ref_at=(0, -2), val_at=(0, 2))
    s.connect(y1, 1, "XL1", stub=2)
    s.connect(y1, 2, "XL2", stub=2)
    cap(s, "C8", 91, 71, "18pF", "C1549", "XL1")
    cap(s, "C9", 101, 71, "18pF", "C1549", "XL2")

    # Площадки SWD снизу под аккумулятором (D-26): только медь, в BOM не входят
    j3 = s.place("Connector_Generic:Conn_01x04", "J3", 96, 92, "SWD",
                 footprint="cricket:SWD_Pads_1x04_P2.54mm", ref_at=(0, -3), val_at=(0, 4), bom=False)
    s.connect(j3, 1, "+3V3")
    s.connect(j3, 2, "SWDIO", stub=6)
    s.connect(j3, 3, "SWDCLK", stub=6)
    s.connect(j3, 4, "GND")
    s.text(84, 103, "J3 — площадки SWD снизу, без деталей, в BOM не входят.\\n1 VDD, 2 SWDIO, 3 SWCLK, 4 GND")


def buzzer_section(s):
    """Шаг 4: PAM8904E, режим 3x, дифференциальный выход на CPT-1117-83 (D-27)."""
    s.text(4, 49, "Пищалка: PAM8904E от VBAT, 1x/2x/3x выбирает прошивка (EN1, EN2), ШИМ ~4,1 кГц на DIN", 1.8)
    u4 = s.place("cricket:PAM8904E", "U4", 30, 60, "PAM8904EGPR",
                 footprint="cricket:Diodes_W-QFN2020-12_2x2mm_P0.4mm_EP1.0x1.0mm", lcsc="C510550",
                 fields={"MPN": "PAM8904EGPR", "Manufacturer": "Diodes Incorporated"})
    s.connect(u4, 12, "VBAT", stub=2)
    s.connect(u4, 1, "BUZ_EN1", stub=2)
    s.connect(u4, 2, "BUZ_EN2", stub=2)
    s.connect(u4, 3, "BUZ_DIN", stub=2)
    s.connect(u4, 9, "BUZ_CP1", stub=2)
    s.connect(u4, 4, "BUZ_CN1", stub=2)
    s.connect(u4, 10, "BUZ_VOUT", stub=2)
    s.connect(u4, 7, "BUZ_P", stub=2)
    s.connect(u4, 6, "BUZ_N", stub=2)
    s.connect(u4, 11, "BUZ_CP2", stub=2)
    s.connect(u4, 8, "BUZ_CN2", stub=2)
    s.connect(u4, 5, "GND")

    cap(s, "C10", 14, 58, "2,2µF 16V", "C23630", "VBAT", fp=C0603)
    cap(s, "C11", 14, 68, "1µF 25V", "C52923", "BUZ_CP1", "BUZ_CN1")
    cap(s, "C12", 46, 68, "1µF 25V", "C52923", "BUZ_CP2", "BUZ_CN2")
    cap(s, "C13", 46, 58, "1µF 25V", "C52923", "BUZ_VOUT")
    cap(s, "C14", 51, 58, "1µF 25V", "C52923", "BUZ_VOUT")

    # CPT-1117-83: на складе LCSC почти нет, JLCPCB закупает через Global Sourcing (D-27)
    bz = s.place("Device:Buzzer", "BZ1", 62, 61, "CPT-1117-83-SMT-TR",
                 footprint="cricket:SameSky_CPT-1117-83-SMT", lcsc="C22359733",
                 fields={"MPN": "CPT-1117-83-SMT-TR", "Manufacturer": "Same Sky"},
                 ref_at=(2, -1.5), val_at=(2, 1.5))
    s.connect(bz, 1, "BUZ_P", stub=2)
    s.connect(bz, 2, "BUZ_N", stub=2)
    s.text(4, 75, "VOUT до 12,6 В при 4,2 В в режиме 3x (предел 13,5 В); размах на излучателе до ~25 В\\n"
                  "при пределе CPT-1117-83 25 В. Режим 3x нельзя при VIN > 4,5 В.")


def io_section(s):
    """Шаг 5: белый светодиод с ключом от VBAT, кнопка, LIS2DH12 по I2C."""
    s.text(96, 5, "Светодиод, кнопка, акселерометр", 1.8)

    # Светодиод от VBAT: (4,2 − 2,9) В / 220 Ом ≈ 6 мА; ключ 2N7002, затвор подтянут к земле
    res(s, "R8", 100, 12, "220Ω", "C25091", "VBAT", "LED_A")
    d2 = s.place("Device:LED", "D2", 100, 19, "KT-0603W", rot=90,
                 footprint="LED_SMD:LED_0603_1608Metric", lcsc="C2290",
                 fields={"MPN": "KT-0603W", "Manufacturer": "Hubei KENTO Elec"},
                 ref_at=(2.5, 0), val_at=(4, 0))
    s.connect(d2, 2, "LED_A")
    s.connect(d2, 1, "LED_K")
    q1 = s.place("Transistor_FET:2N7002", "Q1", 101, 27, "2N7002",
                 footprint="Package_TO_SOT_SMD:SOT-23", lcsc="C8545",
                 fields={"MPN": "2N7002", "Manufacturer": "CJ"}, ref_at=(2, -0.5), val_at=(2, 0.5))
    s.connect(q1, 3, "LED_K")
    s.connect(q1, 2, "GND")
    s.connect(q1, 1, "LED", stub=2)
    res(s, "R9", 94, 30, "10kΩ", "C25744", "LED", "GND")
    s.text(89, 37, "Светодиод выключен,\\nпока GPIO не настроен")

    # Кнопка на GND, подтяжка внутри nRF
    sw1 = s.place("Switch:SW_Push", "SW1", 113, 33, "TS-1088-AR02016",
                  footprint="Button_Switch_SMD:SW_SPST_TS-1088-xR020", lcsc="C720477",
                  fields={"MPN": "TS-1088-AR02016", "Manufacturer": "XUNPU"}, ref_at=(0, -2), val_at=(0, 2))
    s.connect(sw1, 1, "BUTTON", stub=2)
    s.connect(sw1, 2, "GND")

    # LIS2DH12 по I2C (символ LIS2DE12/LIS2HH12 той же разводки LGA-12): CS на VDD_IO — режим I2C,
    # SA0 на VDD_IO — адрес 0x19 и нет тока через внутреннюю подтяжку SA0, вывод 5 (Res) на GND
    u5 = s.place("Sensor_Motion:LIS2DE12", "U5", 130, 24, "LIS2DH12TR",
                 footprint="Package_LGA:LGA-12_2x2mm_P0.5mm", lcsc="C110926",
                 fields={"MPN": "LIS2DH12TR", "Manufacturer": "STMicroelectronics"},
                 ref_at=(-3, -7), val_at=(7, -7))
    s.connect(u5, 1, "I2C_SCL", stub=3)
    s.connect(u5, 4, "I2C_SDA", stub=3)
    # CS и SA0 — общим проводом на +3V3 (провод SA0 пересекает SDA без соединения)
    (cx, cy), _ = u5.pin(2)
    (ax, ay), _ = u5.pin(3)
    k = (cx - G, cy)
    s.wire((cx, cy), k)
    s.wire((ax, ay), (ax - G, ay))
    s.wire(k, (ax - G, ay))
    s.wire(k, (cx - G, cy - G))
    s.junction(k)
    s.power("+3V3", (cx - G, cy - G), (0, -1))
    s.exclude("pin_to_pin", u5, 3, s.parts["U3"], 5,
              "LIS2DH12 SA0 намеренно на +3V3: адрес 0x19, нет тока через внутреннюю подтяжку SA0")
    s.connect(u5, 5, "GND", stub=2)
    s.connect(u5, 12, "ACC_INT1", stub=2)
    s.no_connect(u5, 11)
    s.connect(u5, 9, "+3V3")
    s.connect_pins(u5, 10, u5, 9)
    s.connect(u5, 6, "GND")
    cap(s, "C15", 142, 13, "100nF", "C1525", "+3V3")
    cap(s, "C16", 147, 13, "1µF 25V", "C52923", "+3V3")
    res(s, "R10", 112, 14, "10kΩ", "C25744", "+3V3", "I2C_SCL")
    res(s, "R11", 117, 14, "10kΩ", "C25744", "+3V3", "I2C_SDA")
    s.text(108, 40, "LIS2DH12: I2C, адрес 0x19 (SA0 = 1). INT1 будит модуль по удару.\\n"
                    "C15, C16 — у выводов VDD и VDD_IO.")


def uart_section(s):
    """Шаг 6: последовательные резисторы 1 кОм между полётником и UART модуля."""
    s.text(8, 86, "UART к полётнику: 1 кОм последовательно, защита выводов", 1.8)
    res(s, "R6", 12, 93, "1kΩ", "C11702", "FC_TX", "UART_RX")
    res(s, "R7", 24, 93, "1kΩ", "C11702", "UART_TX", "FC_RX")
    s.text(8, 100, "Без 5 В от полётника UART_TX в прошивке — вход (высокий импеданс),\\n"
                   "чтобы не питать полётник через его защитные диоды.")


def main():
    s = Schematic()
    power_section(s)
    module_section(s)
    buzzer_section(s)
    io_section(s)
    uart_section(s)
    s.write(os.path.join(HERE, "cricket-tag.kicad_sch"))
    s.write_exclusions(os.path.join(HERE, "cricket-tag.kicad_pro"))
    print("ok")


if __name__ == "__main__":
    main()
