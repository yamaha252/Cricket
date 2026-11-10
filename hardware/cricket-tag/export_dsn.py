#!/usr/bin/env python3
"""Выгрузка cricket-tag.kicad_pcb в Specctra DSN для Freerouting.

С --planes перед выгрузкой добавляется заливка GND на нижней стороне: Freerouting
считает её слоем земли и подводит каждую площадку GND переходным, а не дорожкой.
Верхнюю заливку добавляет потом import_ses.py: если отдать Freerouting обе, он
считает площадки сверху подключёнными к верхней заливке, которую затем режут дорожки.

    $KICAD_PY export_dsn.py /tmp/cricket-tag.dsn [--planes]
"""

import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_pcb  # noqa: E402


def main(out, planes):
    board = pcbnew.LoadBoard(gen_pcb.PCB)
    if planes:
        gen_pcb.add_zones(board, layers=(pcbnew.B_Cu,))
    if not pcbnew.ExportSpecctraDSN(board, out):
        raise SystemExit("ExportSpecctraDSN не удался")


if __name__ == "__main__":
    main(sys.argv[1], "--planes" in sys.argv[2:])
