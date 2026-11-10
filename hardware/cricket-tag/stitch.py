#!/usr/bin/env python3
"""Сшивающие переходные GND между заливками верха и низа.

Перебирает точки сетки по плате и ставит переходное 0,5/0,3 мм цепи GND везде,
где оно проходит по зазорам до чужой меди на обоих слоях, не попадает в зону
антенны, под модуль и на площадки. Между сшивающими переходными — не меньше
SPACING. Потом перезаливает зоны.

    $KICAD_PY stitch.py
"""

import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_pcb  # noqa: E402

VIA_D, VIA_DRILL = 0.5, 0.3
CLEAR = 0.15          # до чужой меди, с запасом над 0,13 класса
HOLE_CLEAR = 0.25     # отверстие — отверстие
EDGE = 0.5            # до края платы
STEP = 0.25
SPACING = 1.2
# Переходные, которые сетка не ставит из-за запрета под модулем, от левого верхнего угла платы:
# полоска верхней земли слева от ANNA-B402 (GND 4, 7, 8 и верхний внутренний ряд) иначе
# ни с чем не соединена. Между краем платы и площадками помещается одно 0,5 мм впритык.
EXTRA = [(0.52, 8.92)]


def mm(v):
    return pcbnew.ToMM(v)


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def main():
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    gnd = board.FindNet("GND")
    W, L = gen_pcb.VARIANT()[1:3]
    ox, oy = gen_pcb.OX, gen_pcb.OY
    r = VIA_D / 2

    tracks, vias, boxes = [], [], []
    for t in board.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition()
            vias.append((mm(p.x), mm(p.y), mm(t.GetWidth()) / 2, mm(t.GetDrill()) / 2))
        elif t.GetNetCode() != gnd.GetNetCode():
            s, e = t.GetStart(), t.GetEnd()
            tracks.append((mm(s.x), mm(s.y), mm(e.x), mm(e.y), mm(t.GetWidth()) / 2))
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            bb = pad.GetBoundingBox()
            boxes.append((mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())))

    u1 = board.FindFootprintByReference("U1").GetCourtyard(pcbnew.F_CrtYd).BBox()
    forbidden = [
        (mm(u1.GetLeft()) - 0.3, mm(u1.GetTop()) - 0.3, mm(u1.GetRight()) + 0.3, mm(u1.GetBottom()) + 0.3),
        (ox - 1, oy - 1, ox + 7.6, oy + 5.9),     # зона антенны
    ]

    placed = []
    y = oy + EDGE
    while y <= oy + L - EDGE:
        x = ox + EDGE
        while x <= ox + W - EDGE:
            ok = not any(a - r <= x <= c + r and b - r <= y <= d + r for a, b, c, d in forbidden)
            ok = ok and all(math.hypot(x - px, y - py) >= SPACING for px, py in placed)
            ok = ok and not any(a - r - CLEAR <= x <= c + r + CLEAR and b - r - CLEAR <= y <= d + r + CLEAR
                                for a, b, c, d in boxes)
            ok = ok and all(seg_dist(x, y, ax, ay, bx, by) >= r + w + CLEAR for ax, ay, bx, by, w in tracks)
            ok = ok and all(math.hypot(x - vx, y - vy) >= max(r + vr + CLEAR, VIA_DRILL / 2 + vd + HOLE_CLEAR)
                            for vx, vy, vr, vd in vias)
            if ok:
                placed.append((x, y))
            x += STEP
        y += STEP

    for x, y in EXTRA:
        x, y = ox + x, oy + y
        near = any(math.hypot(x - vx, y - vy) < 0.8 for vx, vy, _r, _d in vias)
        clear = all(seg_dist(x, y, ax, ay, bx, by) >= r + w + CLEAR for ax, ay, bx, by, w in tracks)
        if not near and clear:
            placed.append((x, y))
    for x, y in placed:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        v.SetWidth(pcbnew.FromMM(VIA_D))
        v.SetDrill(pcbnew.FromMM(VIA_DRILL))
        v.SetNet(gnd)
        board.Add(v)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    extra = islands(board, gnd)
    if extra:
        board.BuildConnectivity()
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(gen_pcb.PCB)
    print(f"сшивающих переходных: {len(placed)}, в островках: {extra}")


def islands(board, gnd):
    """Островки заливки без единого переходного GND: ищется точка внутри островка,
    где на другой стороне тоже есть заливка, и туда ставится переходное."""
    sys.path.insert(0, HERE)
    import fanout
    obs = fanout.Obstacles(board)
    fills = {}
    for z in board.Zones():
        if z.GetIsRuleArea() or z.GetParentFootprint() is not None or z.GetNetCode() != gnd.GetNetCode():
            continue
        fills[z.GetLayer()] = z.GetFilledPolysList(z.GetLayer())
    vias = [t.GetPosition() for t in board.GetTracks()
            if t.Type() == pcbnew.PCB_VIA_T and t.GetNetCode() == gnd.GetNetCode()]
    added = 0
    for layer, other in ((pcbnew.F_Cu, pcbnew.B_Cu), (pcbnew.B_Cu, pcbnew.F_Cu)):
        if layer not in fills or other not in fills:
            continue
        polys = fills[layer]
        for k in range(polys.OutlineCount()):
            ol = polys.Outline(k)
            if any(ol.PointInside(v) for v in vias):
                continue
            bb = ol.BBox()
            x0, y0, x1, y1 = mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())
            if (x1 - x0) * (y1 - y0) < 0.3:
                continue
            spot = None
            y = y0
            while y <= y1 and spot is None:
                x = x0
                while x <= x1:
                    p = pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
                    if ol.PointInside(p) and fills[other].Contains(p) and obs.via_ok(x, y, gnd.GetNetCode()):
                        spot = p
                        break
                    x += 0.05
                y += 0.05
            if spot is not None:
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(spot)
                v.SetWidth(pcbnew.FromMM(VIA_D))
                v.SetDrill(pcbnew.FromMM(VIA_DRILL))
                v.SetNet(gnd)
                board.Add(v)
                vias.append(spot)
                added += 1
    return added


if __name__ == "__main__":
    main()
