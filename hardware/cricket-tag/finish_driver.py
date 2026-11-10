#!/usr/bin/env python3
"""Доводка обвязки PAM8904E на уже разведённой плате (D-29).

Freerouting не разводит накачку драйвера: порядок выводов по кругу не даёт сделать это
в один слой, а под драйвером снизу лежат площадки батареи J2. Обвязка задана вручную
в gen_pcb.DRIVER_TRACKS; route.sh ставит её до трассировки. Этот скрипт ставит её на
готовую плату, не трогая остальную разводку:

1. сдвигает детали, чьё место в расстановке floorplan изменилось (C13, C14), вместе
   с концами дорожек на их площадках;
2. снимает старую разводку цепей обвязки и ставит DRIVER_TRACKS / DRIVER_VIAS;
3. снимает чужие незакреплённые дорожки и переходные, которые с ней пересекаются;
4. ведёт OUTP от переходного справа от C12 к излучателю maze.py; дорожки и переходные
   GND ему не мешают, те, что попали под новую дорожку, снимаются — землю держат заливки;
5. снимает висящие обрезки дорожек и переходные.

    $KICAD_PY finish_driver.py
    $KICAD_PY stitch.py      # затем cleanup.py --gnd-vias, пока не вернёт 0, и DRC

Снятые дорожки GND могут оставить карман заливки без связи; его подшивает stitch.py.
"""

import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_pcb  # noqa: E402
import maze  # noqa: E402
from fanout import find_pad, mm  # noqa: E402

DRIVER_NETS = ("/BUZ_VOUT", "/BUZ_CP1", "/BUZ_CP2", "/BUZ_P")
CLEAR = pcbnew.FromMM(0.13)
OUTP_VIA = ("7", (2.5, 1.0))     # из gen_pcb.DRIVER_VIAS
OUTP_TARGET = "BZ1:1"


def move_to_floorplan(board):
    parts = gen_pcb.VARIANT()[0]
    for p in parts:
        ref, x, y = p[1], p[2], p[3]
        fp = board.FindFootprintByReference(ref)
        new = gen_pcb.mm(x, y)
        old = fp.GetPosition()
        if new == old:
            continue
        d = new - old
        centers = {(pad.GetPosition().x, pad.GetPosition().y): pad.GetNetCode() for pad in fp.Pads()}
        for t in board.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                continue
            for get, put in ((t.GetStart, t.SetStart), (t.GetEnd, t.SetEnd)):
                q = get()
                if centers.get((q.x, q.y)) == t.GetNetCode():
                    put(q + d)
        fp.SetPosition(new)
        print(f"{ref}: сдвинут на ({mm(d.x):+.2f}, {mm(d.y):+.2f}) мм")


def layers_of(item):
    if item.Type() == pcbnew.PCB_VIA_T:
        return (pcbnew.F_Cu, pcbnew.B_Cu)
    return (item.GetLayer(),)


def collides(a, b):
    for lay in set(layers_of(a)) & set(layers_of(b)):
        if a.GetEffectiveShape(lay).Collide(b.GetEffectiveShape(lay), CLEAR):
            return True
    return False


def remove_conflicts(board, fixed, soft_only=False):
    """Снимает чужие незакреплённые дорожки и переходные, которые задевают fixed."""
    gone = []
    for t in list(board.GetTracks()):
        if t.IsLocked() or (soft_only and t.GetNetname() != "GND"):
            continue
        if any(t.GetNetCode() != f.GetNetCode() and collides(t, f) for f in fixed):
            gone.append(t.GetNetname())
            board.Delete(t)
    return gone


def remove_dangling(board):
    """Снимает висящие дорожки и переходные (как их видит DRC), пока такие есть."""
    n = 0
    while True:
        board.BuildConnectivity()
        conn = board.GetConnectivity()
        hang = [t for t in board.GetTracks() if conn.TestTrackEndpointDangling(t, False)]
        if not hang:
            return n
        for t in hang:
            p = t.GetPosition()
            print(f"висящее {'переходное' if t.Type() == pcbnew.PCB_VIA_T else 'дорожка'} "
                  f"{t.GetNetname()} ({mm(p.x):.2f}, {mm(p.y):.2f}) снято")
            board.Delete(t)
            n += 1


def route_outp(board):
    u4 = board.FindFootprintByReference("U4").GetPosition()
    vx, vy = mm(u4.x) + OUTP_VIA[1][0], mm(u4.y) + OUTP_VIA[1][1]
    target = find_pad(board, OUTP_TARGET)
    net = target.GetNet()
    w = 0.15
    before = set(t.m_Uuid.AsString() for t in board.GetTracks())
    g = maze.Grid(board, net.GetNetCode(), w, soft=("GND",))
    s = (int(round((vx - g.ox) / maze.STEP)), int(round((vy - g.oy) / maze.STEP)))
    cb, lb = maze.pad_cells(g, target)
    starts = [(s[0], s[1], maze.B)]
    goals = [(i, j, lay) for i, j in cb for lay in lb]
    for st in starts + goals:
        g.block[st[2]][st[1] * g.nx + st[0]] = 0
    path = maze.astar(g, starts, goals)
    if not path:
        return None
    nv = maze.emit(board, g, path, w, net)
    new = [t for t in board.GetTracks() if t.m_Uuid.AsString() not in before]
    gone = remove_conflicts(board, new, soft_only=True)
    length = sum(t.GetLength() for t in new if t.Type() != pcbnew.PCB_VIA_T)
    return nv, mm(length), len(gone)


def main():
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    move_to_floorplan(board)
    for t in list(board.GetTracks()):
        if t.GetNetname() in DRIVER_NETS:
            board.Delete(t)
    before = set(t.m_Uuid.AsString() for t in board.GetTracks())
    n = gen_pcb.driver_routes(board, skip_existing=True)
    fixed = [t for t in board.GetTracks() if t.m_Uuid.AsString() not in before]
    print(f"обвязка драйвера: {n} отрезков и переходных")
    gone = remove_conflicts(board, fixed)
    print("сняты пересекавшие её:", ", ".join(sorted(set(gone))) or "ничего")
    r = route_outp(board)
    if r is None:
        print("OUTP: пути нет")
    else:
        print(f"OUTP: проложено, {r[1]:.1f} мм, переходных {r[0]}, снято GND {r[2]}")
    remove_dangling(board)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(gen_pcb.PCB)


if __name__ == "__main__":
    main()
