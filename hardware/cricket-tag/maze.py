#!/usr/bin/env python3
"""Лабиринтный трассировщик для соединений, которые не развёл Freerouting.

A* на сетке STEP мм по двум слоям, 8 направлений, переход между слоями —
переходное 0,5/0,3 мм там, где оно проходит по зазорам на обоих слоях.
Препятствия — чужая медь (дорожки, переходные, площадки по описанному
прямоугольнику), край платы и зона антенны модуля; заливки не учитываются,
их перезаливает stitch.py. Старт — площадка A, цель — площадка B. Ступеньки сетки
спрямляются по прямой видимости. Grid(soft=…) разрешает пересекать дорожки указанных
цепей за штраф (finish_driver.py так ведёт OUTP поперёк дорожек GND).

    $KICAD_PY maze.py J1:4~R7:2 U1:4~U5:1 NET:/I2C_SCL
"""

import heapq
import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_pcb  # noqa: E402
from fanout import add_track, add_via, find_pad, mm  # noqa: E402

STEP = 0.05
CLEAR = 0.14
EDGE = 0.25
VIA_D, VIA_DRILL, HOLE_CLEAR = 0.5, 0.3, 0.25
VIA_COST = 40
SOFT_COST = 6       # за клетку по мягкой чужой меди
POWER = ("GND", "VBAT", "+5V", "VCHG", "+3V3")
F, B = 0, 1
# Зона антенны и середина под модулем от центра U1 (gen_isp2454.py, D-29): дорожкам и переходным нельзя
KEEPOUT_U1 = [(-5.5, -5.5, 9.5, 0.0), (-2.8, 1.15, 2.8, 2.75)]


class Grid:
    def __init__(self, board, net, w, soft=()):
        """soft — имена цепей, чьи дорожки и переходные можно пересечь за штраф SOFT_COST на клетку
        (GND: перерезанное потом снимается, землю держат заливки)."""
        W, L = gen_pcb.VARIANT()[1:3]
        self.ox, self.oy = gen_pcb.OX, gen_pcb.OY
        self.nx, self.ny = int(W / STEP) + 1, int(L / STEP) + 1
        self.net = net
        n = self.nx * self.ny
        self.block = [bytearray(n), bytearray(n)]   # центр дорожки сюда нельзя
        self.novia = bytearray(n)                   # переходное сюда нельзя
        self.soft = [bytearray(n), bytearray(n)]    # здесь мягкая чужая медь: можно, но дорого
        self.softvia = bytearray(n)
        h = w / 2
        rv = VIA_D / 2
        # край платы
        for j in range(self.ny):
            for i in range(self.nx):
                x, y = i * STEP, j * STEP
                if x < EDGE + h or y < EDGE + h or x > W - EDGE - h or y > L - EDGE - h:
                    self.block[F][j * self.nx + i] = self.block[B][j * self.nx + i] = 1
                if x < EDGE + rv or y < EDGE + rv or x > W - EDGE - rv or y > L - EDGE - rv:
                    self.novia[j * self.nx + i] = 1
        u1 = board.FindFootprintByReference("U1").GetPosition()
        cx, cy = mm(u1.x) - self.ox, mm(u1.y) - self.oy
        for x0, y0, x1, y1 in KEEPOUT_U1:
            self.rect(cx + x0, cy + y0, cx + x1, cy + y1, h, (F, B), via_pad=rv)
        hard = [t for t in board.GetTracks() if t.GetNetname() not in soft]
        self.tracks(hard, net, h, rv)
        if soft:
            self.block, self.soft = self.soft, self.block
            self.novia, self.softvia = self.softvia, self.novia
            self.tracks([t for t in board.GetTracks() if t.GetNetname() in soft], net, h, rv)
            self.block, self.soft = self.soft, self.block
            self.novia, self.softvia = self.softvia, self.novia
        self.pads(board, net, h, rv)

    def tracks(self, items, net, h, rv):
        for t in items:
            if t.Type() == pcbnew.PCB_VIA_T:
                p = t.GetPosition()
                x, y = mm(p.x) - self.ox, mm(p.y) - self.oy
                r = mm(t.GetWidth(pcbnew.F_Cu)) / 2
                same = t.GetNetCode() == net
                if not same:
                    self.disc(x, y, r + CLEAR + h, (F, B))
                    self.disc(x, y, r + CLEAR + rv, (), via=True)
                self.disc(x, y, mm(t.GetDrill()) / 2 + HOLE_CLEAR + VIA_DRILL / 2, (), via=True)
            elif t.GetNetCode() != net:
                s, e = t.GetStart(), t.GetEnd()
                lay = F if t.GetLayer() == pcbnew.F_Cu else B
                self.seg(mm(s.x) - self.ox, mm(s.y) - self.oy, mm(e.x) - self.ox, mm(e.y) - self.oy,
                         mm(t.GetWidth()) / 2 + CLEAR, h, lay, rv)

    def pads(self, board, net, h, rv):
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetCode() == net:
                    continue
                bb = pad.GetBoundingBox()
                lays = tuple(lay for lay, kl in ((F, pcbnew.F_Cu), (B, pcbnew.B_Cu)) if pad.IsOnLayer(kl))
                self.rect(mm(bb.GetLeft()) - self.ox, mm(bb.GetTop()) - self.oy,
                          mm(bb.GetRight()) - self.ox, mm(bb.GetBottom()) - self.oy,
                          h + CLEAR, lays, via_pad=max(rv + CLEAR, VIA_DRILL / 2 + 0.22))

    def idx(self, x, y):
        return int(round(y / STEP)) * self.nx + int(round(x / STEP))

    def cells(self, x0, y0, x1, y1):
        for j in range(max(0, int(y0 / STEP)), min(self.ny, int(y1 / STEP) + 2)):
            for i in range(max(0, int(x0 / STEP)), min(self.nx, int(x1 / STEP) + 2)):
                yield i, j

    def rect(self, x0, y0, x1, y1, grow, lays, via_pad=None):
        R = max(grow, via_pad or 0)
        for i, j in self.cells(x0 - R, y0 - R, x1 + R, y1 + R):
            x, y = i * STEP, j * STEP
            dx = max(x0 - x, 0, x - x1)
            dy = max(y0 - y, 0, y - y1)
            d = math.hypot(dx, dy)
            k = j * self.nx + i
            if d < grow:
                for lay in lays:
                    self.block[lay][k] = 1
            if via_pad is not None and d < via_pad:
                self.novia[k] = 1

    def disc(self, x, y, r, lays, via=False):
        for i, j in self.cells(x - r, y - r, x + r, y + r):
            if math.hypot(i * STEP - x, j * STEP - y) < r:
                k = j * self.nx + i
                for lay in lays:
                    self.block[lay][k] = 1
                if via:
                    self.novia[k] = 1

    def seg(self, ax, ay, bx, by, r, h, lay, rv):
        R = r + max(h, rv)
        for i, j in self.cells(min(ax, bx) - R, min(ay, by) - R, max(ax, bx) + R, max(ay, by) + R):
            x, y = i * STEP, j * STEP
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            t = 0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
            d = math.hypot(x - ax - t * dx, y - ay - t * dy)
            k = j * self.nx + i
            if d < r + h:
                self.block[lay][k] = 1
            if d < r + rv:
                self.novia[k] = 1


def pad_cells(g, pad):
    bb = pad.GetBoundingBox()
    x0, y0 = mm(bb.GetLeft()) - g.ox, mm(bb.GetTop()) - g.oy
    x1, y1 = mm(bb.GetRight()) - g.ox, mm(bb.GetBottom()) - g.oy
    c = pad.GetPosition()
    cx, cy = mm(c.x) - g.ox, mm(c.y) - g.oy
    # середина площадки, чтобы конец дорожки был внутри меди
    m = 0.4
    out = []
    for i, j in g.cells(x0 + (x1 - x0) * m / 2, y0 + (y1 - y0) * m / 2, x1 - (x1 - x0) * m / 2, y1 - (y1 - y0) * m / 2):
        if x0 <= i * STEP <= x1 and y0 <= j * STEP <= y1:
            out.append((i, j))
    lays = [lay for lay, kl in ((F, pcbnew.F_Cu), (B, pcbnew.B_Cu)) if pad.IsOnLayer(kl)]
    return out or [(int(round(cx / STEP)), int(round(cy / STEP)))], lays


def astar(g, starts, goals):
    goal = set(goals)
    gx = sum(i for i, _, _ in goals) / len(goals)
    gy = sum(j for _, j, _ in goals) / len(goals)

    def hcost(i, j):
        return math.hypot(i - gx, j - gy)

    openq, came, cost = [], {}, {}
    for s in starts:
        cost[s] = 0
        heapq.heappush(openq, (hcost(s[0], s[1]), 0, s))
    dirs = [(1, 0, 1), (-1, 0, 1), (0, 1, 1), (0, -1, 1), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
    n = 0
    while openq:
        _, c, cur = heapq.heappop(openq)
        if cur in goal:
            path = [cur]
            while path[-1] in came:
                path.append(came[path[-1]])
            return path[::-1]
        if c > cost.get(cur, 1e18):
            continue
        n += 1
        if n > 2_000_000:
            return None
        i, j, lay = cur
        nbrs = []
        for di, dj, dc in dirs:
            ni, nj = i + di, j + dj
            if 0 <= ni < g.nx and 0 <= nj < g.ny and not g.block[lay][nj * g.nx + ni]:
                nbrs.append(((ni, nj, lay), dc + SOFT_COST * g.soft[lay][nj * g.nx + ni]))
        k = j * g.nx + i
        if not g.novia[k] and not g.block[1 - lay][k]:
            nbrs.append(((i, j, 1 - lay), VIA_COST + SOFT_COST * (g.softvia[k] + g.soft[1 - lay][k])))
        for nxt, dc in nbrs:
            nc = c + dc
            if nc < cost.get(nxt, 1e18):
                cost[nxt] = nc
                came[nxt] = cur
                heapq.heappush(openq, (nc + hcost(nxt[0], nxt[1]), nc, nxt))
    return None


def route(board, spec):
    wforce = None
    if "@" in spec:   # A~B@0.15 — ширина дорожки вместо ширины класса цепи
        spec, wforce = spec.split("@")
    sa, sb = spec.split("~")
    pa, pb = find_pad(board, sa), find_pad(board, sb)
    netinfo = pa.GetNet()
    w = float(wforce) if wforce else (0.25 if netinfo.GetNetname() in POWER else 0.15)
    g = Grid(board, pa.GetNetCode(), w)
    ca, la = pad_cells(g, pa)
    cb, lb = pad_cells(g, pb)
    starts = [(i, j, lay) for i, j in ca for lay in la]
    goals = [(i, j, lay) for i, j in cb for lay in lb]
    for s in starts + goals:   # площадки свои, их клетки свободны
        g.block[s[2]][s[1] * g.nx + s[0]] = 0
    path = astar(g, starts, goals)
    if not path:
        return f"{spec}: пути нет"
    nvias = emit(board, g, path, w, netinfo)
    return f"{spec}: проложено, переходных {nvias}"


def clear_line(g, a, b):
    """Отрезок между клетками a и b на одном слое не задевает препятствий сетки."""
    n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) * 4))
    blk, soft = g.block[a[2]], g.soft[a[2]]
    for k in range(n + 1):
        i = int(round(a[0] + (b[0] - a[0]) * k / n))
        j = int(round(a[1] + (b[1] - a[1]) * k / n))
        if blk[j * g.nx + i] or soft[j * g.nx + i]:
            return False
    return True


def simplify(g, pts):
    """Спрямление по прямой видимости: ступеньки сетки в длинные отрезки, переходные на месте."""
    out = [pts[0]]
    i = 0
    while i < len(pts) - 1:
        j = i + 1
        if pts[j][2] == pts[i][2]:
            k = j
            while k + 1 < len(pts) and pts[k + 1][2] == pts[i][2] and clear_line(g, pts[i], pts[k + 1]):
                k += 1
            j = k
        out.append(pts[j])
        i = j
    return out


def emit(board, g, path, w, netinfo):
    """Путь A* в дорожки и переходные на плате; возвращает число переходных."""
    # отрезки: подряд идущие шаги одного направления на одном слое
    pts = [path[0]]
    for a, b, c in zip(path, path[1:], path[2:]):
        if a[2] != b[2] or b[2] != c[2] or (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]):
            pts.append(b)
    pts.append(path[-1])
    pts = simplify(g, pts)
    xy = lambda p: (g.ox + p[0] * STEP, g.oy + p[1] * STEP)  # noqa: E731
    lay_k = (pcbnew.F_Cu, pcbnew.B_Cu)
    nvias = 0
    for a, b in zip(pts, pts[1:]):
        if a[2] != b[2]:
            add_via(board, xy(a), netinfo)
            nvias += 1
        elif a != b:
            add_track(board, xy(a), xy(b), w, lay_k[a[2]], netinfo)
    return nvias


def net_specs(board, name):
    """Пары площадок цепи по минимальному остовному дереву (Прим) от центров площадок."""
    pads = [(fp.GetReference(), p.GetNumber(), mm(p.GetPosition().x), mm(p.GetPosition().y))
            for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetname() == name]
    uniq = {}
    for ref, num, x, y in pads:
        uniq.setdefault((ref, num), (x, y))
    keys = list(uniq)
    if len(keys) < 2:
        return []
    done, specs = [keys[0]], []
    rest = keys[1:]
    while rest:
        a, b = min(((a, b) for a in done for b in rest),
                   key=lambda ab: math.dist(uniq[ab[0]], uniq[ab[1]]))
        specs.append(f"{a[0]}:{a[1]}~{b[0]}:{b[1]}")
        done.append(b)
        rest.remove(b)
    return specs


def main(specs):
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    todo = []
    for s in specs:
        todo += net_specs(board, s[4:]) if s.startswith("NET:") else [s]
    for s in todo:
        r = route(board, s)
        if r.endswith("пути нет") and "@" not in s:
            pa = find_pad(board, s.split("~")[0])
            if pa.GetNetname() in POWER:
                r = route(board, s + "@0.15") + " (0,15 мм)"
        print(r, flush=True)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(gen_pcb.PCB)


if __name__ == "__main__":
    main(sys.argv[1:])
