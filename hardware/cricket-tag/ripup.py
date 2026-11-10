#!/usr/bin/env python3
"""Снятие разводки цепей (незакреплённые дорожки и переходные) перед перекладкой maze.py.

    $KICAD_PY ripup.py /I2C_SCL /I2C_SDA
"""

import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_pcb  # noqa: E402


def main(nets):
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    dead = [t for t in board.GetTracks() if not t.IsLocked() and t.GetNetname() in nets]
    for t in dead:
        board.Remove(t)
    board.Save(gen_pcb.PCB)
    print(len(dead))


if __name__ == "__main__":
    main(sys.argv[1:])
