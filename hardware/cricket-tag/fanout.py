#!/usr/bin/env python3
"""Отвод площадок на переходное там, где Freerouting их не подключил.

Для каждой площадки REF:PAD ищет рядом место под переходное 0,5/0,3 мм и прямой
отрезок дорожки от площадки до него, которые проходят по зазорам до чужой меди.
Площадки GND так попадают на нижнюю заливку. С целью REF:PAD@REF2:PAD2 переходное
выбирается так, чтобы от него прямой дорожкой по другому слою дойти до площадки
REF2:PAD2 (например, +5V с верхней стороны на площадку провода снизу).

    $KICAD_PY fanout.py C6:2 U4:5 R1:1@J1:1
"""

import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_pcb  # noqa: E402

VIA_D, VIA_DRILL = 0.5, 0.3
CLEAR = 0.14
HOLE_CLEAR = 0.25
EDGE = 0.4


def mm(v):
    return pcbnew.ToMM(v)


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def seg_seg(a, b, c, d):
    if _intersect(a, b, c, d):
        return 0.0
    return min(seg_dist(*a, *c, *d), seg_dist(*b, *c, *d), seg_dist(*c, *a, *b), seg_dist(*d, *a, *b))


def _intersect(p1, p2, p3, p4):
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2, d3, d4 = ccw(p3, p4, p1), ccw(p3, p4, p2), ccw(p1, p2, p3), ccw(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def seg_box(a, b, box):
    x0, y0, x1, y1 = box
    if x0 <= a[0] <= x1 and y0 <= a[1] <= y1 or x0 <= b[0] <= x1 and y0 <= b[1] <= y1:
        return 0.0
    edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
    return min(seg_seg(a, b, e0, e1) for e0, e1 in edges)


class Obstacles:
    def __init__(self, board):
        self.tracks, self.vias, self.pads = [], [], []
        for t in board.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                p = t.GetPosition()
                self.vias.append((mm(p.x), mm(p.y), mm(t.GetWidth(pcbnew.F_Cu)) / 2, mm(t.GetDrill()) / 2,
                                  t.GetNetCode()))
            else:
                s, e = t.GetStart(), t.GetEnd()
                self.tracks.append(((mm(s.x), mm(s.y)), (mm(e.x), mm(e.y)), mm(t.GetWidth()) / 2,
                                    t.GetLayer(), t.GetNetCode()))
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                bb = pad.GetBoundingBox()
                layers = [lay for lay in (pcbnew.F_Cu, pcbnew.B_Cu) if pad.IsOnLayer(lay)]
                self.pads.append(((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())),
                                  layers, pad.GetNetCode(), pad))

    def via_ok(self, x, y, net):
        r = VIA_D / 2
        for vx, vy, vr, vd, vn in self.vias:
            d = math.hypot(x - vx, y - vy)
            if d < VIA_DRILL / 2 + vd + HOLE_CLEAR or (vn != net and d < r + vr + CLEAR):
                return False
        for a, b, w, _lay, n in self.tracks:
            if n != net and seg_dist(x, y, *a, *b) < r + w + CLEAR:
                return False
        for (x0, y0, x1, y1), layers, n, _p in self.pads:
            if n == net and layers == [pcbnew.B_Cu]:
                continue   # переходное в нижней площадке провода той же цепи — так и задумано
            gap = r + (CLEAR if n != net else 0.05)
            if x0 - gap <= x <= x1 + gap and y0 - gap <= y <= y1 + gap:
                return False
        return True

    def seg_ok(self, a, b, w, layer, net, skip_pads=()):
        h = w / 2
        for c, d, tw, lay, n in self.tracks:
            if lay == layer and n != net and seg_seg(a, b, c, d) < h + tw + CLEAR:
                return False
        for vx, vy, vr, _vd, vn in self.vias:
            if vn != net and seg_dist(vx, vy, *a, *b) < h + vr + CLEAR:
                return False
        for box, layers, n, pad in self.pads:
            if layer in layers and n != net and pad not in skip_pads and seg_box(a, b, box) < h + CLEAR:
                return False
        return True


def add_track(board, a, b, w, layer, net):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(a[0]), pcbnew.FromMM(a[1])))
    t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(b[0]), pcbnew.FromMM(b[1])))
    t.SetWidth(pcbnew.FromMM(w))
    t.SetLayer(layer)
    t.SetNet(net)
    board.Add(t)


def add_via(board, p, net):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(p[0]), pcbnew.FromMM(p[1])))
    v.SetWidth(pcbnew.FromMM(VIA_D))
    v.SetDrill(pcbnew.FromMM(VIA_DRILL))
    v.SetNet(net)
    board.Add(v)


def find_pad(board, spec):
    ref, num = spec.split(":")
    return next(p for p in board.FindFootprintByReference(ref).Pads() if p.GetNumber() == num)


def fan(board, spec, W, L):
    target = None
    if "@" in spec:
        spec, tspec = spec.split("@")
        target = find_pad(board, tspec)
    pad = find_pad(board, spec)
    net = pad.GetNet()
    layer = pcbnew.F_Cu if pad.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
    other = pcbnew.B_Cu if layer == pcbnew.F_Cu else pcbnew.F_Cu
    pc = pad.GetPosition()
    px, py = mm(pc.x), mm(pc.y)
    w = 0.25 if net.GetNetname() in ("GND", "VBAT", "+5V", "VCHG", "+3V3") else 0.15
    obs = Obstacles(board)
    x0, y0 = gen_pcb.OX + EDGE, gen_pcb.OY + EDGE
    x1, y1 = gen_pcb.OX + W - EDGE, gen_pcb.OY + L - EDGE
    best = None
    for i in range(-24, 25):
        for j in range(-24, 25):
            x, y = px + i * 0.1, py + j * 0.1
            d = math.hypot(x - px, y - py)
            if d > 2.4 or not (x0 <= x <= x1 and y0 <= y <= y1) or (best and d >= best[0]):
                continue
            if not obs.via_ok(x, y, net.GetNetCode()):
                continue
            if not obs.seg_ok((px, py), (x, y), w, layer, net.GetNetCode(), skip_pads=(pad,)):
                continue
            if target is not None:
                tc = target.GetPosition()
                t = (mm(tc.x), mm(tc.y))
                if not obs.seg_ok((x, y), t, w, other, net.GetNetCode(), skip_pads=(target,)):
                    continue
            best = (d, x, y)
    if not best:
        return f"{spec}: места нет"
    _, x, y = best
    add_track(board, (px, py), (x, y), w, layer, net)
    add_via(board, (x, y), net)
    if target is not None:
        tc = target.GetPosition()
        add_track(board, (x, y), (mm(tc.x), mm(tc.y)), w, other, net)
    return f"{spec}: переходное в ({x - gen_pcb.OX:.2f}, {y - gen_pcb.OY:.2f})"


def main(specs):
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    W, L = gen_pcb.VARIANT()[1:3]
    for s in specs:
        print(fan(board, s, W, L))
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(gen_pcb.PCB)


if __name__ == "__main__":
    main(sys.argv[1:])
