#!/usr/bin/env python3
"""Загрузка разводки Freerouting (.ses) в cricket-tag.kicad_pcb и перезаливка зон.

Порядок разводки (подробно в README платы, раздел «Разводка»):

    KICAD_PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
    $KICAD_PY gen_pcb.py /tmp/cricket.net          # детали, цепи, контур, зоны
    $KICAD_PY -c "import pcbnew; pcbnew.ExportSpecctraDSN(pcbnew.LoadBoard('cricket-tag.kicad_pcb'), '/tmp/cricket-tag.dsn')"
    java -jar freerouting.jar -de /tmp/cricket-tag.dsn -do /tmp/cricket-tag.ses -mp 60 --gui.enabled=false
    $KICAD_PY import_ses.py /tmp/cricket-tag.ses

Запуск только питоном KiCad (нужен модуль pcbnew).
"""

import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, "cricket-tag.kicad_pcb")


def main(ses):
    board = pcbnew.LoadBoard(PCB)
    for t in list(board.GetTracks()):
        if not t.IsLocked():   # закреплённый вывод из-под модуля (gen_pcb.module_escape) остаётся
            board.Remove(t)
    if not pcbnew.ImportSpecctraSES(board, ses):
        raise SystemExit("ImportSpecctraSES не удался")
    sys.path.insert(0, HERE)
    import gen_pcb
    gen_pcb.add_zones(board)
    board.Save(PCB)
    n_tracks = sum(1 for t in board.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T)
    n_vias = sum(1 for t in board.GetTracks() if t.Type() == pcbnew.PCB_VIA_T)
    print(f"дорожек {n_tracks}, переходных {n_vias}")


if __name__ == "__main__":
    main(sys.argv[1])
