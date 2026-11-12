#!/usr/bin/env python3
"""Уборка готовой разводки: то, что остаётся неряшливым после Freerouting и maze.py.

    $KICAD_PY tidy.py gnd      # лишние дорожки GND
    $KICAD_PY tidy.py dust     # пыль из отрезков внутри площадок
    $KICAD_PY tidy.py merge    # микросегменты и лесенки
    $KICAD_PY tidy.py widen    # тонкие дорожки
    $KICAD_PY tidy.py vias     # второе переходное островкам заливки

gnd   — GND разводится дорожками как обычная цепь, потом сверху ложится заливка, и большая
        часть этих дорожек оказывается внутри сплошной земли: зигзаги поперёк площадок,
        обрезанные термобарьеры, щели в заливке. Каждая незакреплённая дорожка GND по
        очереди снимается; если после перезаливки вся плата осталась связной, дорожка
        лишняя. Иначе возвращается на место.
dust  — Freerouting подводит дорожку к площадке гребёнкой из отрезков по 0,003 мм разной
        ширины. Незакреплённые отрезки короче DUST, оба конца которых лежат внутри одной
        площадки своей цепи, снимаются: всё, что к ним подходило, остаётся на меди площадки.
merge — цепочки отрезков одной цепи, слоя и ширины без ответвлений: отрезки на одной
        прямой склеиваются, лесенки сетки maze.py (шаги по 0,05 мм) заменяются парой
        «прямая + 45°» или одной прямой, если новая дорожка проходит по зазорам.
widen — дорожки уже WIDE расширяются до WIDE там, где до чужой меди остаётся зазор;
        закреплённые (обвязка драйвера, вывод из-под модуля) не трогаются.

vias  — островок заливки GND, который держится на одном переходном, получает второе:
        одно непропаянное или треснувшее отверстие не должно отрывать от земли площадки
        островка, а обратный ток конденсаторов не должен идти через единственное отверстие.
        Место — внутри островка, с заливкой на другой стороне, как можно дальше от первого.
        Под модулем, в зоне антенны и у площадок под пайку переходные не ставятся.

После каждого прохода — DRC. Каждая команда — отдельный процесс: после board.Remove
SWIG KiCad 10 отдаёт сырые объекты, поэтому всё читается до первой правки.
"""

import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_pcb  # noqa: E402
from fanout import seg_dist, seg_seg, seg_box  # noqa: E402

CLEAR = 0.14          # до чужой меди, с запасом над 0,13 класса
EDGE = 0.25           # до кромки платы
WIDE = 0.15
DUST = 0.1
PARK = pcbnew.Cmts_User   # сюда дорожка уходит на время проверки: board.Remove ломает SWIG


def mm(v):
    return pcbnew.ToMM(v)


def refill(board):
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    return board.GetConnectivity().GetUnconnectedCount(False)


def prune_gnd():
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    gnd = board.FindNet("GND").GetNetCode()
    cand = [t for t in board.GetTracks()
            if t.Type() == pcbnew.PCB_TRACE_T and t.GetNetCode() == gnd and not t.IsLocked()]
    cand.sort(key=lambda t: -t.GetLength())
    layer = {id(t): t.GetLayer() for t in cand}
    base = refill(board)
    if base:
        raise SystemExit(f"до уборки уже {base} неподключённых")
    drop = []
    for t in cand:
        t.SetLayer(PARK)      # без цепи и вне меди: в связности не участвует
        t.SetNetCode(0)
        if refill(board) == 0:
            drop.append(t)
        else:
            t.SetLayer(layer[id(t)])
            t.SetNetCode(gnd)
    refill(board)
    for t in drop:
        board.Remove(t)
    board.Save(gen_pcb.PCB)
    print(f"дорожек GND: {len(cand)}, лишних снято: {len(drop)}")


class Copper:
    """Чужая медь для проверки зазоров новой дорожки: дорожки, переходные, площадки (по описанному
    прямоугольнику), кромка платы и зона антенны. Заливки не учитываются — они перезаливаются."""

    def __init__(self, board):
        self.ox, self.oy = gen_pcb.OX, gen_pcb.OY
        self.W, self.L = gen_pcb.VARIANT()[1:3]
        self.tracks, self.vias, self.pads = [], [], []
        for t in board.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                p = t.GetPosition()
                self.vias.append((t.GetNetCode(), mm(p.x), mm(p.y), mm(t.GetWidth(pcbnew.F_Cu)) / 2))
            elif t.Type() == pcbnew.PCB_TRACE_T:
                s, e = t.GetStart(), t.GetEnd()
                self.tracks.append((t.GetNetCode(), t.GetLayer(), (mm(s.x), mm(s.y)), (mm(e.x), mm(e.y)),
                                    mm(t.GetWidth()) / 2))
        wire = pcbnew.FromMM(gen_pcb.WIRE_PAD_GAP - CLEAR + 0.01)
        for fp in board.GetFootprints():
            grow = wire if fp.GetReference() in ("J1", "J2") else 0   # правило wire_pad_clearance
            for pad in fp.Pads():
                bb = pad.GetBoundingBox()
                lays = [kl for kl in (pcbnew.F_Cu, pcbnew.B_Cu) if pad.IsOnLayer(kl)]
                self.pads.append((pad.GetNetCode(), lays, (mm(bb.GetLeft() - grow), mm(bb.GetTop() - grow),
                                                           mm(bb.GetRight() + grow), mm(bb.GetBottom() + grow))))
        u1 = board.FindFootprintByReference("U1").GetPosition()
        cx, cy = mm(u1.x), mm(u1.y)
        # зона антенны и середина под модулем, как в maze.py
        self.keepout = [(cx - 5.5, cy - 5.5, cx + 9.5, cy), (cx - 2.8, cy + 1.15, cx + 2.8, cy + 2.75)]

    def ok(self, net, layer, a, b, h, skip=()):
        """Отрезок a–b полушириной h на слое layer проходит по зазорам. skip — отрезки, которые он заменяет."""
        for p in (a, b):
            if not (self.ox + EDGE + h <= p[0] <= self.ox + self.W - EDGE - h
                    and self.oy + EDGE + h <= p[1] <= self.oy + self.L - EDGE - h):
                return False
        if any(seg_box(a, b, k) < h for k in self.keepout):
            return False
        for n, lay, s, e, w in self.tracks:
            if n != net and lay == layer and seg_seg(a, b, s, e) < h + w + CLEAR:
                return False
        for n, x, y, r in self.vias:
            if n != net and seg_dist(x, y, *a, *b) < h + r + CLEAR:
                return False
        for n, lays, box in self.pads:
            if n != net and layer in lays and seg_box(a, b, box) < h + CLEAR:
                return False
        return True


def chains(board):
    """Цепочки отрезков одной цепи и слоя, в узлах ровно два конца и ничего больше
    (ни переходного, ни площадки, ни третьей дорожки). Закреплённые отрезки не входят.
    Ширина внутри цепочки может меняться: Freerouting сужает дорожку у площадок пылью
    из отрезков по 0,003 мм разной ширины."""
    key = lambda p: (round(p[0], 4), round(p[1], 4))   # noqa: E731
    segs = []
    for t in board.GetTracks():
        if t.Type() == pcbnew.PCB_TRACE_T:
            s, e = t.GetStart(), t.GetEnd()
            segs.append({"t": t, "net": t.GetNetCode(), "lay": t.GetLayer(), "w": mm(t.GetWidth()),
                         "a": (mm(s.x), mm(s.y)), "b": (mm(e.x), mm(e.y)), "locked": t.IsLocked()})
    hard = set()   # узлы, где цепочку рвать: переходные и центры площадок
    for t in board.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition()
            hard.add(key((mm(p.x), mm(p.y))))
    boxes = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            bb = pad.GetBoundingBox()
            boxes.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))
    in_pad = lambda p: any(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for x0, y0, x1, y1 in boxes)  # noqa: E731
    node = {}
    for s in segs:
        for end in ("a", "b"):
            node.setdefault((s["net"], s["lay"], key(s[end])), []).append(s)
    # узел на любом слое занят чужим слоем той же цепи — тоже рвать (стык без переходного не бывает, но на всякий случай)
    used, out = set(), []
    for s0 in segs:
        if id(s0) in used or s0["locked"]:
            continue
        chain = [s0]
        used.add(id(s0))
        pts = [s0["a"], s0["b"]]
        for head in (False, True):
            while True:
                p = pts[0] if head else pts[-1]
                k = (s0["net"], s0["lay"], key(p))
                nb = node[k]
                if len(nb) != 2 or key(p) in hard or in_pad(p):
                    break
                nxt = nb[0] if nb[1] is chain[0 if head else -1] else nb[1]
                if id(nxt) in used or nxt["locked"]:
                    break
                used.add(id(nxt))
                q = nxt["b"] if key(nxt["a"]) == key(p) else nxt["a"]
                if head:
                    chain.insert(0, nxt)
                    pts.insert(0, q)
                else:
                    chain.append(nxt)
                    pts.append(q)
        out.append((chain, pts))
    return out


def is45(a, b):
    dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
    return dx < 1e-4 or dy < 1e-4 or abs(dx - dy) < 1e-4


def doglegs(a, b):
    """Пути из a в b из отрезков под 0/45/90°: прямая, если уже такая, иначе два варианта излома."""
    if is45(a, b):
        return [[a, b]]
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = min(abs(dx), abs(dy))
    sx, sy = math.copysign(d, dx), math.copysign(d, dy)
    m1 = (a[0] + sx, a[1] + sy)            # сначала диагональ
    m2 = (b[0] - sx, b[1] - sy)            # сначала прямая
    return [[a, m2, b], [a, m1, b]]


def merge():
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    cu = Copper(board)
    todo, shorter = [], 0
    for chain, pts in chains(board):
        if len(chain) < 2:
            continue
        s0 = chain[0]
        net, lay = s0["net"], s0["lay"]
        # вершины, которые остаются: начало, конец и настоящие повороты (длинные отрезки с обеих сторон)
        keep = [0]
        i = 0
        n = len(pts)
        while i < n - 1:
            # самый дальний j, до которого из i доходит прямая или излом по зазорам
            best = None
            for j in range(n - 1, i, -1):
                if j == i + 1:
                    break
                part = chain[i:j]
                long = [s["w"] for s in part if math.dist(s["a"], s["b"]) >= 0.1] or [s["w"] for s in part]
                for w in sorted({max(long), min(s["w"] for s in part)}, reverse=True):
                    for path in doglegs(pts[i], pts[j]):
                        if all(cu.ok(net, lay, p, q, w / 2) for p, q in zip(path, path[1:])):
                            best = (j, path, w)
                            break
                    if best:
                        break
                if best:
                    break
            if best:
                todo.append((chain[i:best[0]], best[1], dict(s0, w=best[2])))
                shorter += best[0] - i - (len(best[1]) - 1)
                i = best[0]
            else:
                i += 1
    new, old = [], []
    for segs, path, s0 in todo:
        if len(path) - 1 >= len(segs):
            continue
        old += segs
        new.append((path, s0))
    for path, s0 in new:
        for p, q in zip(path, path[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(p[0]), pcbnew.FromMM(p[1])))
            t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(q[0]), pcbnew.FromMM(q[1])))
            t.SetWidth(pcbnew.FromMM(s0["w"]))
            t.SetLayer(s0["lay"])
            t.SetNetCode(s0["net"])
            board.Add(t)
    for s in old:
        board.Remove(s["t"])
    refill(board)
    board.Save(gen_pcb.PCB)
    print(f"отрезков снято: {len(old)}, проложено: {sum(len(p) - 1 for p, _ in new)}")


def dust():
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    pads = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetShape(pad.GetPrincipalLayer()) in (pcbnew.PAD_SHAPE_RECTANGLE, pcbnew.PAD_SHAPE_ROUNDRECT):
                bb = pad.GetBoundingBox()
                m = 0.05   # запас на скруглённые углы
                pads.append((pad.GetNetCode(), [kl for kl in (pcbnew.F_Cu, pcbnew.B_Cu) if pad.IsOnLayer(kl)],
                             mm(bb.GetLeft()) + m, mm(bb.GetTop()) + m, mm(bb.GetRight()) - m, mm(bb.GetBottom()) - m))
    drop = []
    for t in board.GetTracks():
        if t.Type() != pcbnew.PCB_TRACE_T or t.IsLocked() or mm(t.GetLength()) >= DUST:
            continue
        ends = [(mm(p.x), mm(p.y)) for p in (t.GetStart(), t.GetEnd())]
        if any(n == t.GetNetCode() and t.GetLayer() in lays and all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in ends)
               for n, lays, x0, y0, x1, y1 in pads):
            drop.append(t)
    for t in drop:
        board.Remove(t)
    left = refill(board)
    board.Save(gen_pcb.PCB)
    print(f"пыли снято: {len(drop)}, неподключённых: {left}")


def widen():
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    cu = Copper(board)
    n = left = 0
    for t in board.GetTracks():
        if t.Type() != pcbnew.PCB_TRACE_T or t.IsLocked() or mm(t.GetWidth()) >= WIDE - 1e-6:
            continue
        s, e = t.GetStart(), t.GetEnd()
        if cu.ok(t.GetNetCode(), t.GetLayer(), (mm(s.x), mm(s.y)), (mm(e.x), mm(e.y)), WIDE / 2):
            t.SetWidth(pcbnew.FromMM(WIDE))
            n += 1
        else:
            left += 1
    refill(board)
    board.Save(gen_pcb.PCB)
    print(f"расширено до {WIDE} мм: {n}, осталось тонких: {left}")


def more_vias():
    import fanout
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    gnd = board.FindNet("GND")
    code = gnd.GetNetCode()
    obs = fanout.Obstacles(board)
    ox, oy = gen_pcb.OX, gen_pcb.OY
    W, L = gen_pcb.VARIANT()[1:3]
    r = fanout.VIA_D / 2
    # под модулем (по его площадкам: курятник ISP2454-LX тянется на всю зону антенны) и зона антенны
    u1 = [p.GetBoundingBox() for p in board.FindFootprintByReference("U1").Pads()]
    forbidden = [(mm(min(k.GetLeft() for k in u1)) - 0.3, mm(min(k.GetTop() for k in u1)) - 0.3,
                  mm(max(k.GetRight() for k in u1)) + 0.3, mm(max(k.GetBottom() for k in u1)) + 0.3),
                 (ox - 1, oy - 1, ox + 14.8, oy + 5.5)]
    g = gen_pcb.WIRE_PAD_GAP + r + 0.01
    for ref in ("J1", "J2"):
        for pad in board.FindFootprintByReference(ref).Pads():
            if pad.GetNetCode() != code:
                bb = pad.GetBoundingBox()
                forbidden.append((mm(bb.GetLeft()) - g, mm(bb.GetTop()) - g, mm(bb.GetRight()) + g, mm(bb.GetBottom()) + g))
    fills = {}
    for z in board.Zones():
        if not z.GetIsRuleArea() and z.GetParentFootprint() is None and z.GetNetCode() == code:
            fills[z.GetLayer()] = z.GetFilledPolysList(z.GetLayer())
    vias = [(mm(t.GetPosition().x), mm(t.GetPosition().y)) for t in board.GetTracks()
            if t.Type() == pcbnew.PCB_VIA_T and t.GetNetCode() == code]
    ring = [(math.cos(a * math.pi / 4), math.sin(a * math.pi / 4)) for a in range(8)]
    pt = lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))   # noqa: E731
    new = []
    for layer, other in ((pcbnew.F_Cu, pcbnew.B_Cu), (pcbnew.B_Cu, pcbnew.F_Cu)):
        polys = fills[layer]
        for k in range(polys.OutlineCount()):
            ol = polys.Outline(k)
            if mm(mm(ol.Area())) < 0.5:
                continue
            inside = [v for v in vias + new if ol.PointInside(pt(*v))]
            if len(inside) >= 2:
                continue
            bb = ol.BBox()
            best = None
            y = max(mm(bb.GetTop()), oy + fanout.EDGE)
            while y <= min(mm(bb.GetBottom()), oy + L - fanout.EDGE):
                x = max(mm(bb.GetLeft()), ox + fanout.EDGE)
                while x <= min(mm(bb.GetRight()), ox + W - fanout.EDGE):
                    far = min((math.hypot(x - vx, y - vy) for vx, vy in vias + new), default=9)
                    if (far >= 0.8 and (best is None or far > best[0])
                            and not any(a <= x <= c and b <= y <= d for a, b, c, d in forbidden)
                            and all(ol.PointInside(pt(x + (r + 0.05) * cx, y + (r + 0.05) * cy)) for cx, cy in ring)
                            and all(fills[other].Contains(pt(x + r * cx, y + r * cy)) for cx, cy in ring)
                            and obs.via_ok(x, y, code)):
                        best = (far, x, y)
                    x += 0.05
                y += 0.05
            if best:
                new.append((best[1], best[2]))
    for x, y in new:
        fanout.add_via(board, (x, y), gnd)
    left = refill(board)
    board.Save(gen_pcb.PCB)
    print(f"переходных добавлено: {len(new)}: " + ", ".join(f"({x - ox:.2f}, {y - oy:.2f})" for x, y in new)
          + f"; неподключённых: {left}")


if __name__ == "__main__":
    {"gnd": prune_gnd, "dust": dust, "merge": merge, "widen": widen, "vias": more_vias}[sys.argv[1]]()
