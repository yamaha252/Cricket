#!/usr/bin/env python3
"""Досоединение пар площадок одной цепи, которые Freerouting оставил.

Для пары REF:PAD~REF2:PAD2 пробует по порядку:
  1. прямой отрезок на слое площадок;
  2. Г-образный путь через угол на сетке 0,1 мм;
  3. переходные рядом с каждой площадкой и прямой или Г-образный путь по другому слою.
Каждый отрезок проверяется на зазоры до чужой меди (fanout.Obstacles).

    $KICAD_PY connect.py R4:2~C3:1 J1:4~R7:2
"""

import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fanout  # noqa: E402
import gen_pcb  # noqa: E402
from fanout import add_track, add_via, find_pad, mm  # noqa: E402

POWER = ("GND", "VBAT", "+5V", "VCHG", "+3V3")


def pad_xy(p):
    c = p.GetPosition()
    return mm(c.x), mm(c.y)


def layer_of(p):
    return pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu


def path_ok(obs, pts, w, layer, net, skip):
    return all(obs.seg_ok(a, b, w, layer, net, skip) for a, b in zip(pts, pts[1:]))


def l_paths(a, b):
    yield [a, b]
    yield [a, (b[0], a[1]), b]
    yield [a, (a[0], b[1]), b]
    # обход через точку сетки рядом с отрезком
    for k in range(1, 16):
        for s in (1, -1):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy) or 1
            nx, ny = -dy / L * 0.2 * k * s, dx / L * 0.2 * k * s
            m = ((a[0] + b[0]) / 2 + nx, (a[1] + b[1]) / 2 + ny)
            yield [a, m, b]


def via_spots(obs, p, net, layer, w, skip, limit=2.0):
    px, py = p
    out = []
    for i in range(-20, 21):
        for j in range(-20, 21):
            x, y = px + i * 0.1, py + j * 0.1
            d = math.hypot(x - px, y - py)
            if d > limit or not obs.via_ok(x, y, net):
                continue
            if obs.seg_ok(p, (x, y), w, layer, net, skip):
                out.append((d, (x, y)))
    return [q for _, q in sorted(out)[:25]]


def connect(board, spec):
    sa, sb = spec.split("~")
    pa, pb = find_pad(board, sa), find_pad(board, sb)
    net = pa.GetNet()
    code = net.GetNetCode()
    w = 0.25 if net.GetNetname() in POWER else 0.15
    obs = fanout.Obstacles(board)
    a, b = pad_xy(pa), pad_xy(pb)
    la, lb = layer_of(pa), layer_of(pb)
    skip = (pa, pb)
    if la == lb:
        for pts in l_paths(a, b):
            if path_ok(obs, pts, w, la, code, skip):
                for p, q in zip(pts, pts[1:]):
                    add_track(board, p, q, w, la, net)
                return f"{spec}: дорожка по {board.GetLayerName(la)}"
    other = pcbnew.B_Cu if la == pcbnew.F_Cu else pcbnew.F_Cu
    va = via_spots(obs, a, code, la, w, skip)
    vb = via_spots(obs, b, code, lb, w, skip) if lb == la else [b]
    for x in va:
        for y in vb:
            for pts in l_paths(x, y):
                if path_ok(obs, pts, w, other, code, skip):
                    add_track(board, a, x, w, la, net)
                    add_via(board, x, net)
                    for p, q in zip(pts, pts[1:]):
                        add_track(board, p, q, w, other, net)
                    if lb == la:
                        add_via(board, y, net)
                        add_track(board, y, b, w, lb, net)
                    return f"{spec}: через переходные по {board.GetLayerName(other)}"
    return f"{spec}: не получилось"


def repair(board):
    """Обрывы после Freerouting: концы дорожек одной цепи на одном слое ближе 0,3 мм
    сращиваются; концы на разных слоях в одной точке без переходного получают переходное."""
    board.BuildConnectivity()
    conn = board.GetConnectivity()
    ends = []
    for t in board.GetTracks():
        if t.Type() == pcbnew.PCB_TRACE_T:
            for p in (t.GetStart(), t.GetEnd()):
                ends.append((mm(p.x), mm(p.y), t.GetLayer(), t.GetNetCode(), t))
    vias = {(round(mm(v.GetPosition().x), 3), round(mm(v.GetPosition().y), 3))
            for v in board.GetTracks() if v.Type() == pcbnew.PCB_VIA_T}
    obs = fanout.Obstacles(board)
    done = []
    for i, (x, y, lay, n, t) in enumerate(ends):
        for x2, y2, lay2, n2, t2 in ends[i + 1:]:
            if n != n2 or t is t2:
                continue
            d = math.hypot(x - x2, y - y2)
            net = t.GetNet()
            w = mm(t.GetWidth())
            if lay == lay2 and 0.001 < d < 0.3 and conn.TestTrackEndpointDangling(t, False):
                if obs.seg_ok((x, y), (x2, y2), w, lay, n, ()):
                    add_track(board, (x, y), (x2, y2), w, lay, net)
                    done.append(f"срощено {net.GetNetname()} ({x - gen_pcb.OX:.2f}, {y - gen_pcb.OY:.2f})")
            elif lay != lay2 and d < 0.01 and (round(x, 3), round(y, 3)) not in vias:
                if obs.via_ok(x, y, n) and (conn.TestTrackEndpointDangling(t, False) or conn.TestTrackEndpointDangling(t2, False)):
                    add_via(board, (x, y), net)
                    vias.add((round(x, 3), round(y, 3)))
                    done.append(f"переходное {net.GetNetname()} ({x - gen_pcb.OX:.2f}, {y - gen_pcb.OY:.2f})")
    return done


def main(specs):
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    for s in specs:
        if s == "repair":
            for line in repair(board):
                print(line, flush=True)
            continue
        print(connect(board, s), flush=True)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(gen_pcb.PCB)


if __name__ == "__main__":
    main(sys.argv[1:])
