#!/usr/bin/env python3
"""Уборка после Freerouting: висящие переходные и обрывки дорожек.

Удаляет незакреплённые дорожки и переходные с висящим концом и печатает их число.
Обрывок может висеть на другом обрывке, поэтому запускать, пока не напечатает 0
(в одном процессе вторую загрузку платы SWIG KiCad 10 не переносит):

    while [ "$($KICAD_PY cleanup.py | tail -1)" != 0 ]; do :; done

С --gnd-vias удаляет и переходные GND, которые после заливки соединены только
с одним слоем (сшивающее переходное в островке без заливки на другой стороне).
"""

import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_pcb  # noqa: E402


def one_pass():
    """Удаляет висящие элементы, возвращает их число."""
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    board.BuildConnectivity()
    conn = board.GetConnectivity()
    gnd = board.FindNet("GND").GetNetCode()
    gnd_vias = "--gnd-vias" in sys.argv
    dead = [t for t in board.GetTracks()
            if not t.IsLocked() and conn.TestTrackEndpointDangling(t, False)
            and (t.GetNetCode() != gnd or (gnd_vias and t.Type() == pcbnew.PCB_VIA_T))]
    for t in dead:
        board.Remove(t)
    if not dead:
        board.BuildConnectivity()
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(gen_pcb.PCB)
    return len(dead)


def main():
    """Один проход на процесс: вторую плату в том же процессе SWIG KiCad 10 не обслуживает.
    Запускать в цикле, пока печатает не ноль."""
    print(one_pass())


if __name__ == "__main__":
    main()
