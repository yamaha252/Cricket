#!/usr/bin/env python3
"""Плата cricket-tag из схемы: детали по расстановке floorplan (вариант w17d),
цепи из списка соединений, контур, закреплённый вывод цепей из-под модуля
(module_escape). Остальная разводка — Freerouting, затем import_ses.py, который
добавляет заливки GND (add_zones): во время трассировки GND разводится как
обычная цепь, иначе Freerouting оставляет землю рваной.

Запуск только питоном KiCad (нужен модуль pcbnew):

    KICAD_PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
    kicad-cli sch export netlist cricket-tag.kicad_sch -o /tmp/cricket.net
    $KICAD_PY gen_pcb.py /tmp/cricket.net
    $KICAD_PY gen_pcb.py --fields /tmp/cricket.net   # только поля LCSC/MPN в готовой плате

Без --fields перезаписывает cricket-tag.kicad_pcb: дорожки, если были, пропадут.
"""

import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
sys.path.insert(0, os.path.join(HERE, "floorplan"))
from symlib import parse, unq  # noqa: E402
import floorplan  # noqa: E402

STD = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
VARIANT = floorplan.variant_w17d
OX, OY = 100.0, 100.0          # левый верхний угол платы на листе, мм
PCB = os.path.join(HERE, "cricket-tag.kicad_pcb")


def mm(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(OX + x), pcbnew.FromMM(OY + y))


def items(tree, key):
    return [t for t in tree if isinstance(t, list) and t and t[0] == key]


def first(tree, key):
    r = items(tree, key)
    return r[0] if r else None


FIELDS = ("LCSC Part", "MPN", "Manufacturer")  # переносятся из символов в футпринты


def set_fields(fp, fields):
    for name, val in fields.items():
        fp.SetField(name, val)
        f = fp.GetField(name)
        if f is not None:
            f.SetVisible(False)
            f.SetLayer(pcbnew.F_Fab)


def sync_fields(netlist):
    """Только поля LCSC Part / MPN / Manufacturer в футпринтах разведённой платы, без перестройки."""
    comps, _ = read_netlist(netlist)
    board = pcbnew.LoadBoard(PCB)
    for ref, c in comps.items():
        fp = board.FindFootprintByReference(ref)
        if fp is not None:
            set_fields(fp, c["fields"])
    board.Save(PCB)


def read_netlist(path):
    tree = parse(open(path).read())
    comps, nets = {}, []
    for c in items(first(tree, "components"), "comp"):
        ref = unq(first(c, "ref")[1])
        fields = {}
        for f in items(first(c, "fields") or [], "field"):
            name = unq(first(f, "name")[1])
            val = [unq(x) for x in f[2:] if not isinstance(x, list)]
            if name in FIELDS and val and val[0]:
                fields[name] = val[0]
            elif name == "Datasheet":   # совпадает со схемой, даже пустое
                fields[name] = val[0] if val else ""
        comps[ref] = {
            "value": unq(first(c, "value")[1]),
            "footprint": unq(first(c, "footprint")[1]) if first(c, "footprint") else "",
            "tstamp": unq(first(c, "tstamps")[1]),
            "fields": fields,
        }
    for n in items(first(tree, "nets"), "net"):
        name = unq(first(n, "name")[1])
        nodes = [(unq(first(x, "ref")[1]), unq(first(x, "pin")[1])) for x in items(n, "node")]
        nets.append((name, nodes))
    return comps, nets


def load_fp(fpid):
    lib, name = fpid.split(":")
    path = os.path.join(HERE, "lib", "cricket.pretty") if lib == "cricket" else os.path.join(STD, lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise SystemExit(f"нет футпринта {fpid}")
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


KEEP = ("version", "generator", "generator_version", "general", "paper", "title_block", "layers", "setup",
        "embedded_fonts")


def pristine_board():
    """Плата только с заголовком, слоями и настройками: всё остальное выбрасывается из текста.
    Удалять элементы через pcbnew нельзя: GetDrawings() в KiCad 10 из питона падает."""
    from symlib import sexpr_end
    text = open(PCB).read()
    out, pos = [text[:text.index("\n") + 1]], text.index("\n") + 1
    while True:
        i = text.find("(", pos)
        if i < 0:
            break
        e = sexpr_end(text, i)
        key = text[i + 1:e].split(None, 1)[0].rstrip(")")
        if key in KEEP:
            out.append("\t" + text[i:e] + "\n")
        pos = e
    out.append(")\n")
    # Пишется на место платы, чтобы pcbnew подхватил cricket-tag.kicad_pro: плата, загруженная
    # из другой папки, при сохранении перезаписала бы проект настройками по умолчанию.
    with open(PCB, "w") as fh:
        fh.write("".join(out))
    return pcbnew.LoadBoard(PCB)


def outline(board, W, L):
    pts = [(0, 0), (W, 0), (W, L), (0, L)]
    for i in range(4):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(mm(*pts[i]))
        s.SetEnd(mm(*pts[(i + 1) % 4]))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(pcbnew.FromMM(0.05))
        board.Add(s)


_keep = []


def gnd_zone(board, net, layer, W, L, priority=0):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(net)
    z.SetAssignedPriority(priority)
    z.SetLocalClearance(pcbnew.FromMM(0.2))
    z.SetMinThickness(pcbnew.FromMM(0.2))
    z.SetThermalReliefGap(pcbnew.FromMM(0.25))
    z.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.25))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    # z.Outline() иногда приходит из SWIG без обёртки, поэтому контур собирается отдельно
    o = pcbnew.SHAPE_POLY_SET()
    o.NewOutline()
    for x, y in ((0, 0), (W, 0), (W, L), (0, L)):
        p = mm(x, y)
        o.Append(p.x, p.y)
    z.SetOutline(o)
    _keep.append(o)  # SetOutline хранит указатель: контур не должен уйти в сборщик мусора
    board.Add(z)
    return z


# Вывод из-под ANNA-B402, координаты от центра модуля (D-24, D-28). Внутренние
# ряды на двух слоях иначе не вывести: зазоры между площадками 0,3 мм.
#  - GND 43–46 (верхний внутренний ряд) соединены между собой и с GND 4 на левом столбце;
#  - центральные GND 53–56 — на переходное 0,5/0,3 мм в середине между ними;
#  - SWDIO 42 и SWDCLK 41 — на переходные в свободном месте под модулем справа сверху,
#    вне зоны антенны, дальше по нижнему слою к J3.
ESCAPE_TRACKS = [  # (цепь, ширина, (x, y)...)
    ("GND", 0.2, (0, -1.435), (-0.65, -1.435), (-1.3, -1.435), (-1.95, -1.435)),
    ("GND", 0.15, (-1.95, -1.435), (-2.84, -0.598)),
    ("GND", 0.2, (0, 0.702), (-0.52, 0.252)),
    ("GND", 0.2, (0, 0.702), (0.52, 0.252)),
    ("GND", 0.2, (0, 0.702), (-0.52, 1.152)),
    ("GND", 0.2, (0, 0.702), (0.52, 1.152)),
    ("/SWDIO", 0.15, (0.65, -1.435), (0.8, -2.55)),
    ("/SWDCLK", 0.15, (1.3, -1.435), (1.65, -2.2)),
]
ESCAPE_VIAS = [("GND", 0.5, 0.3, (0, 0.702)), ("/SWDIO", 0.5, 0.3, (0.8, -2.55)), ("/SWDCLK", 0.5, 0.3, (1.65, -2.2))]


def driver_ground(board, netinfo):
    """PAM8904E: переходное в центральной площадке (13) на нижнюю землю и вывод 5 к ней.
    Площадка окружена выводами, заливка сверху к ней не подходит."""
    u4 = board.FindFootprintByReference("U4")
    ep = next(p for p in u4.Pads() if p.GetNumber() == "13").GetPosition()
    p5 = next(p for p in u4.Pads() if p.GetNumber() == "5").GetPosition()
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(p5)
    t.SetEnd(ep)
    t.SetWidth(pcbnew.FromMM(0.25))
    t.SetLayer(pcbnew.F_Cu)
    t.SetNet(netinfo["GND"])
    t.SetLocked(True)
    board.Add(t)
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(ep)
    v.SetWidth(pcbnew.FromMM(0.5))
    v.SetDrill(pcbnew.FromMM(0.3))
    v.SetNet(netinfo["GND"])
    v.SetLocked(True)
    board.Add(v)


def module_escape(board, netinfo):
    u1 = board.FindFootprintByReference("U1")
    c = u1.GetPosition()

    def at(p):
        return pcbnew.VECTOR2I(c.x + pcbnew.FromMM(p[0]), c.y + pcbnew.FromMM(p[1]))

    for net, w, *pts in ESCAPE_TRACKS:
        for a, b in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(at(a))
            t.SetEnd(at(b))
            t.SetWidth(pcbnew.FromMM(w))
            t.SetLayer(pcbnew.F_Cu)
            t.SetNet(netinfo[net])
            t.SetLocked(True)
            board.Add(t)
    for net, d, drill, p in ESCAPE_VIAS:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(at(p))
        v.SetWidth(pcbnew.FromMM(d))
        v.SetDrill(pcbnew.FromMM(drill))
        v.SetNet(netinfo[net])
        v.SetLocked(True)
        board.Add(v)


def add_zones(board, layers=(pcbnew.F_Cu, pcbnew.B_Cu)):
    """Заливки GND по контуру платы, по умолчанию на обеих сторонах."""
    for z in list(board.Zones()):
        if not z.GetIsRuleArea() and z.GetParentFootprint() is None:
            board.Remove(z)
    W, L = VARIANT()[1:3]
    gnd = board.FindNet("GND")
    for layer in layers:
        gnd_zone(board, gnd, layer, W, L)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())


def silk_text(board, text, x, y, layer, size=0.8, angle=0):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetPosition(mm(x, y))
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
    t.SetTextThickness(pcbnew.FromMM(0.15))
    t.SetTextAngleDegrees(angle)
    if layer == pcbnew.B_SilkS:
        t.SetMirrored(True)
    board.Add(t)


def swd_labels(board):
    """Подписи площадок SWD J3 на нижней стороне: 1 VDD, 2 SWDIO, 3 SWCLK, 4 GND."""
    j3 = board.FindFootprintByReference("J3")
    for pad, txt in zip(sorted(j3.Pads(), key=lambda p: p.GetNumber()), ("V", "IO", "CK", "G")):
        pos = pad.GetPosition()
        silk_text(board, txt, pcbnew.ToMM(pos.x) - OX, pcbnew.ToMM(pos.y) - OY + 1.4, pcbnew.B_SilkS, 0.8)


def main(netlist):
    comps, nets = read_netlist(netlist)
    parts, W, L, _battery = VARIANT()
    place = {p[1]: p for p in parts}

    board = pristine_board()
    outline(board, W, L)

    missing = sorted(set(comps) - set(place))
    extra = sorted(set(place) - set(comps))
    if missing or extra:
        raise SystemExit(f"расстановка и схема расходятся: нет места для {missing}, лишние {extra}")

    for ref, c in sorted(comps.items()):
        fpid, _r, x, y, *rest = place[ref]
        rot = rest[0] if rest else 0
        side = rest[1] if len(rest) > 1 else "F"
        if c["footprint"] and c["footprint"] != fpid:
            raise SystemExit(f"{ref}: в схеме {c['footprint']}, в расстановке {fpid}")
        fp = load_fp(fpid)
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetPath(pcbnew.KIID_PATH(f"/{c['tstamp']}"))
        board.Add(fp)
        set_fields(fp, c["fields"])
        fp.SetPosition(mm(x, y))
        fp.SetOrientationDegrees(rot)
        if side == "B":
            fp.Flip(mm(x, y), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        # Плата слишком плотная для позиционных обозначений на шелкографии: они остаются на Fab
        fp.Reference().SetVisible(False)

    netinfo = {}
    for name, nodes in nets:
        n = pcbnew.NETINFO_ITEM(board, name)
        board.Add(n)
        netinfo[name] = n
        for ref, pin in nodes:
            fp = board.FindFootprintByReference(ref)
            hit = [p for p in fp.Pads() if p.GetNumber() == pin]
            if not hit:
                raise SystemExit(f"{ref}: нет площадки {pin} для цепи {name}")
            for p in hit:
                p.SetNet(n)

    module_escape(board, netinfo)
    driver_ground(board, netinfo)

    # Подписи площадок под провода на нижней стороне
    j1 = board.FindFootprintByReference("J1")
    j2 = board.FindFootprintByReference("J2")
    for fp, names in ((j1, ("5V", "G", "TX", "RX")), (j2, ("+", "−"))):
        for pad, txt in zip(sorted(fp.Pads(), key=lambda p: p.GetNumber()), names):
            pos = pad.GetPosition()
            silk_text(board, txt, pcbnew.ToMM(pos.x) - OX, pcbnew.ToMM(pos.y) - OY + 1.9, pcbnew.B_SilkS, 0.8)
    swd_labels(board)

    board.Save(PCB)
    print(f"{len(comps)} деталей, {len(nets)} цепей, плата {W} × {L} мм")


if __name__ == "__main__":
    if sys.argv[1] == "--fields":
        sync_fields(sys.argv[2])
    elif sys.argv[1] == "--swd-labels":   # только подписи J3 на готовой плате
        _b = pcbnew.LoadBoard(PCB)
        swd_labels(_b)
        _b.Save(PCB)
    else:
        main(sys.argv[1])
