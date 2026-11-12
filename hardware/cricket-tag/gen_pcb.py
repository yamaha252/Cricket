#!/usr/bin/env python3
"""Плата cricket-tag из схемы: детали по расстановке floorplan (вариант isp_c, D-29),
цепи из списка соединений, контур, закреплённый вывод цепей из-под модуля
(module_escape) и обвязка драйвера пищалки (driver_ground, driver_routes). Остальная разводка — Freerouting, затем import_ses.py, который
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
VARIANT = floorplan.variant_isp_c
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


# Вывод из-под ISP2454-LX, координаты от центра модуля (D-29): антенная половина вверху (−Y),
# верхний ряд выводов внизу (+Y). Между площадками 0,25 мм — дорожка не проходит, поэтому:
#  - GND 8 к угловой GND 7; GND 21–23–24 к угловой GND 25; центральные GND 12–18 не подключены;
#  - угловые GND — на свои переходные: 25 — в полосе у левой кромки над VDD, 7 — в пустой
#    середине под модулем, 31 — сразу за корпусом. Иначе Freerouting ставит их у зоны антенны.
#    Для GND 1 место выбирает Freerouting: своё переходное перекрывало путь к акселерометру;
#  - OUT_MOD 22 ↔ OUT_ANT 20 перемычкой вдоль ряда;
#  - UART_RX с внутренней площадки 29 (P0.00) на переходное в середине под модулем,
#    закрытое маской, дальше по нижнему слою;
#  - VDD 26, SWDIO 28, SWDCLK 30 — по полосе 1,3 мм между модулем и левой кромкой вниз,
#    за курятник модуля, на переходные лесенкой; дальше разводит Freerouting. К концу дорожки
#    без переходного Freerouting не подключается.
# Цепь задаётся площадкой модуля ("pad:N"): имена неименованных цепей зависят от KiCad.
ESCAPE_TRACKS = [  # (цепь, ширина, (x, y)...)
    ("pad:7", 0.2, (2.6, 0.2), (3.3, 0.2)),
    ("pad:7", 0.2, (3.1, 0.8), (2.4, 1.55)),
    ("pad:25", 0.2, (-2.6, 0.2), (-3.3, 0.2)),
    ("pad:25", 0.2, (-2.275, 0.85), (-2.6, 0.2)),
    ("pad:25", 0.2, (-1.625, 0.85), (-2.275, 0.85)),
    ("pad:25", 0.25, (-3.5, 0.6), (-4.65, 0.6)),
    ("pad:31", 0.25, (-3.5, 3.5), (-3.5, 4.75)),
    ("pad:20", 0.2, (-1.95, 0.2), (-1.3, 0.2)),
    ("pad:29", 0.15, (-3.05, 2.275), (-2.1, 1.95)),
    # VDD, SWDIO, SWDCLK вдоль левой кромки (x платы 0,35 / 0,68 / 1,01) и на переходные под модулем
    ("pad:26", 0.15, (-3.7, 1.3), (-4.95, 1.3), (-4.95, 7.2), (-4.7, 7.6)),
    ("pad:28", 0.15, (-3.7, 1.95), (-4.62, 1.95), (-4.62, 6.2), (-4.45, 6.6)),
    ("pad:30", 0.15, (-3.7, 2.6), (-4.29, 2.6), (-4.29, 5.0), (-4.05, 5.5)),
    # ACC_INT1: с верхнего ряда (48) к INT1 акселерометра наверху его корпуса. Напрямую путь
    # перекрыт I2C и каналом под модулем: переходное справа от модуля, вверх по нижнему слою
    # под самим модулем (полоса справа на нижнем слое остаётся свободной), второе переходное
    # у U5, сверху к INT1 вдоль границы зоны антенны
    ("pad:48", 0.15, (2.6, 3.7), (2.6, 4.4), (4.35, 4.4), (4.35, 4.5)),
    ("pad:48", 0.15, "B", (4.35, 4.5), (3.3, 3.45), (3.3, 1.2), (4.35, 0.35)),
    ("pad:48", 0.15, (4.35, 0.35), (4.35, 0.2), (5.65, 0.2), (5.65, 0.64)),
]
ESCAPE_VIAS = [("pad:29", 0.5, 0.3, (-2.1, 1.95)), ("pad:7", 0.5, 0.3, (2.4, 1.55)),
               ("pad:25", 0.5, 0.3, (-4.65, 0.6)), ("pad:31", 0.5, 0.3, (-3.5, 4.75)),
               ("pad:26", 0.5, 0.3, (-4.7, 7.6)), ("pad:28", 0.5, 0.3, (-4.45, 6.6)),
               ("pad:30", 0.5, 0.3, (-4.05, 5.5)),
               ("pad:48", 0.5, 0.3, (4.35, 4.5)), ("pad:48", 0.5, 0.3, (4.35, 0.35))]


def driver_ground(board, netinfo):
    """PAM8904E: переходное в центральной площадке (13) на нижнюю землю и вывод 5 к ней.
    Площадка окружена выводами, заливка сверху к ней не подходит. Снизу под драйвером лежат
    площадки батареи J2, между ними медь не нужна (перемычка припоя при пайке провода замкнёт
    батарею), поэтому переходное сдвинуто к краю площадки, к J2.2 (GND), и соединено с ней дорожкой."""
    u4 = board.FindFootprintByReference("U4")
    ep = next(p for p in u4.Pads() if p.GetNumber() == "13").GetPosition()
    p5 = next(p for p in u4.Pads() if p.GetNumber() == "5").GetPosition()
    via = pcbnew.VECTOR2I(ep.x - pcbnew.FromMM(0.245), ep.y)
    for a, b, layer in ((p5, ep, pcbnew.F_Cu), (via, pcbnew.VECTOR2I(ep.x - pcbnew.FromMM(0.6), ep.y), pcbnew.B_Cu)):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(a)
        t.SetEnd(b)
        t.SetWidth(pcbnew.FromMM(0.25))
        t.SetLayer(layer)
        t.SetNet(netinfo["GND"])
        t.SetLocked(True)
        board.Add(t)
    # Минус батареи J2.2 снизу зажат дорожками VBAT и BUZ_DIN и площадкой J2.1: к нижней земле ему
    # не выйти. Второе переходное внутри J2.2 выводит его на верхнюю заливку под U4.3 и U4.4, чтобы весь
    # ток батареи не шёл через одно отверстие в центральной площадке драйвера (D-41).
    for at in (via, pcbnew.VECTOR2I(ep.x - pcbnew.FromMM(1.025), ep.y + pcbnew.FromMM(0.975))):
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(at)
        v.SetWidth(pcbnew.FromMM(0.5))
        v.SetDrill(pcbnew.FromMM(0.3))
        v.SetNet(netinfo["GND"])
        v.SetLocked(True)
        board.Add(v)


# Площадки под ручную пайку проводов (J1 — полётник, J2 — батарея): заливка между ними и
# ближе WIRE_PAD_GAP не нужна, чужие дорожки и переходные держит на том же расстоянии правило
# wire_pad_clearance в cricket-tag.kicad_dru. Между площадками 0,8 мм, так что дорожка 0,15 мм
# по середине проходит с зазором 0,325 мм.
WIRE_PAD_GAP = 0.3


def wire_pad_keepouts(board):
    """Зоны без заливки на нижнем слое вокруг J1 и J2. Старые с тем же именем заменяются."""
    g = pcbnew.FromMM(WIRE_PAD_GAP)
    rects = {}
    for ref in ("J1", "J2"):   # читать до board.Remove: после него SWIG KiCad 10 отдаёт сырые объекты
        boxes = [p.GetBoundingBox() for p in board.FindFootprintByReference(ref).Pads()]
        rects[ref] = (min(b.GetLeft() for b in boxes) - g, min(b.GetTop() for b in boxes) - g,
                      max(b.GetRight() for b in boxes) + g, max(b.GetBottom() for b in boxes) + g)
    for z in [z for z in board.Zones() if z.GetIsRuleArea() and z.GetZoneName().startswith("wire-pads-")]:
        board.Remove(z)
    for ref, (x0, y0, x1, y1) in rects.items():
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetZoneName(f"wire-pads-{ref}")
        z.SetLayer(pcbnew.B_Cu)
        z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowTracks(False)
        z.SetDoNotAllowVias(False)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        o = pcbnew.SHAPE_POLY_SET()
        o.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            o.Append(x, y)
        z.SetOutline(o)
        _keep.append(o)
        board.Add(z)


# Обвязка PAM8904E (D-29), точки от центра U4. Порядок выводов по кругу — 12 VBAT, 11 CP2,
# 10 VOUT, 9 CP1, 8 CN2, 7 OUTP — не даёт развести накачку в один слой, а снизу под драйвером
# лежат площадки батареи J2, так что переходные стоят только вокруг них. Freerouting сам
# эти связи не находит. CP2 уходит вниз переходным между C10 и C13 и выходит к C12;
# CP1 — переходным над J2 и по низу справа от J2 к C11; VOUT по диагонали к C13 и C14;
# VBAT вывода 12 — переходным прямо на J2.1; OUTP — к переходному справа от C12,
# дальше к излучателю разводит Freerouting или maze.py. Всё, что идёт по низу, держится не ближе
# WIRE_PAD_GAP (0,3 мм) к площадкам J2: их паяют руками.
DRIVER_TRACKS = [   # (вывод U4, ширина, слой, точки…)
    ("12", 0.25, "F", (-0.4, -0.9), (-0.4, -1.407), (-1.032, -1.407), (-1.775, -2.15)),
    ("12", 0.25, "F", (-0.9, -1.275), (-0.9, -1.407)),
    ("12", 0.25, "B", (-0.9, -1.275), (0.75, -1.275), (0.75, -0.4)),
    # 0,12 мм: щель между углом C10.2 и выводом 10 — 0,41 мм
    ("11", 0.12, "F", (0.0, -0.9), (0.0, -1.162), (0.63, -1.792), (0.63, -2.15)),
    ("11", 0.15, "B", (0.63, -2.15), (1.55, -2.15), (2.3, -1.4)),
    ("11", 0.15, "F", (2.3, -1.4), (2.3, -0.68)),
    ("10", 0.15, "F", (0.4, -0.9), (0.4, -1.15), (0.77, -1.52), (1.275, -1.52), (1.275, -3.1)),
    ("9", 0.15, "F", (0.9, -0.4), (1.3, -0.4), (1.675, -0.775), (1.675, -1.255)),
    ("9", 0.15, "B", (1.675, -1.255), (1.775, -1.255), (2.105, -0.925), (2.105, 1.425), (1.005, 2.525)),
    ("9", 0.15, "F", (1.005, 2.525), (0.48, 2.0)),
    ("7", 0.15, "F", (0.9, 0.4), (1.35, 0.4), (1.95, 1.0), (2.625, 1.0)),
]
DRIVER_VIAS = [("12", (-0.9, -1.275)), ("11", (0.63, -2.15)), ("11", (2.3, -1.4)),
               ("9", (1.675, -1.255)), ("9", (1.005, 2.525)), ("7", (2.625, 1.0))]


def driver_routes(board, skip_existing=False):
    """Закреплённая обвязка драйвера по DRIVER_TRACKS и DRIVER_VIAS. skip_existing — не дублировать
    отрезки и переходные, которые уже есть на плате (доводка готовой платы, finish_driver.py)."""
    u4 = board.FindFootprintByReference("U4")
    c = u4.GetPosition()
    pads = {p.GetNumber(): p for p in u4.Pads()}

    def at(p):
        return pcbnew.VECTOR2I(c.x + pcbnew.FromMM(p[0]), c.y + pcbnew.FromMM(p[1]))

    have = set()
    if skip_existing:
        for t in board.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                have.add(("V", t.GetNetCode(), t.GetPosition().x, t.GetPosition().y))
            else:
                a, b = sorted([(t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)])
                have.add((t.GetLayer(), t.GetNetCode(), a, b))
    n = 0
    for pin, w, lay, *pts in DRIVER_TRACKS:
        net = pads[pin].GetNet()
        layer = pcbnew.B_Cu if lay == "B" else pcbnew.F_Cu
        for a, b in zip(pts, pts[1:]):
            A, B = at(a), at(b)
            key = (layer, net.GetNetCode(), *sorted([(A.x, A.y), (B.x, B.y)]))
            if key in have:
                continue
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(A)
            t.SetEnd(B)
            t.SetWidth(pcbnew.FromMM(w))
            t.SetLayer(layer)
            t.SetNet(net)
            t.SetLocked(True)
            board.Add(t)
            n += 1
    for pin, p in DRIVER_VIAS:
        net = pads[pin].GetNet()
        P = at(p)
        if ("V", net.GetNetCode(), P.x, P.y) in have:
            continue
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(P)
        v.SetWidth(pcbnew.FromMM(0.5))
        v.SetDrill(pcbnew.FromMM(0.3))
        v.SetNet(net)
        v.SetLocked(True)
        board.Add(v)
        n += 1
    return n


def module_escape(board, netinfo):
    u1 = board.FindFootprintByReference("U1")
    c = u1.GetPosition()
    pads = {p.GetNumber(): p for p in u1.Pads()}

    def net_of(name):
        if name.startswith("pad:"):
            return pads[name[4:]].GetNet()
        return netinfo[name]

    def at(p):
        return pcbnew.VECTOR2I(c.x + pcbnew.FromMM(p[0]), c.y + pcbnew.FromMM(p[1]))

    for net, w, *pts in ESCAPE_TRACKS:
        layer = pcbnew.F_Cu
        if isinstance(pts[0], str):
            layer = pcbnew.B_Cu if pts[0] == "B" else pcbnew.F_Cu
            pts = pts[1:]
        for a, b in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(at(a))
            t.SetEnd(at(b))
            t.SetWidth(pcbnew.FromMM(w))
            t.SetLayer(layer)
            t.SetNet(net_of(net))
            t.SetLocked(True)
            board.Add(t)
    for net, d, drill, p in ESCAPE_VIAS:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(at(p))
        v.SetWidth(pcbnew.FromMM(d))
        v.SetDrill(pcbnew.FromMM(drill))
        v.SetNet(net_of(net))
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
    driver_routes(board)
    wire_pad_keepouts(board)

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
