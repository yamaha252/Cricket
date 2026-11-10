#!/usr/bin/env python3
"""Сужения Freerouting у площадок (дорожки уже 0,1 мм) — до 0,1 мм, минимума JLCPCB и DRC.

    $KICAD_PY widen.py
"""

import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_pcb  # noqa: E402

MIN = pcbnew.FromMM(0.1)


def main():
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    n = 0
    for t in board.GetTracks():
        if t.Type() == pcbnew.PCB_TRACE_T and t.GetWidth() < MIN:
            t.SetWidth(MIN)
            n += 1
    board.Save(gen_pcb.PCB)
    print(n)


if __name__ == "__main__":
    main()
