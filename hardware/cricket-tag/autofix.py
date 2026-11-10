#!/usr/bin/env python3
"""Что доделать после Freerouting, по отчёту DRC (kicad-cli pcb drc -o drc.rpt).

Печатает строки для route.sh:
  MAZE A~B ...  — пары площадок одной цепи без связи: проложить maze.py;
  RIP цепи      — сигнальные цепи с обрывами дорожек: снять и проложить заново целиком;
  FAN площадки  — одиночные площадки GND: отвести на переходное fanout.py.

    python3 autofix.py drc.rpt [цепи, которые снять целиком]
"""

import re
import sys

ITEM = re.compile(r"(?:Pad (\S+) )?\[([^\]]+)\](?: of (\S+))?")


def main(rpt, again=()):
    """again — цепи, которые прошлый круг не довёл парой площадок: их снимать целиком."""
    text = open(rpt).read()
    maze, rip, fan = [], [], []
    for block in re.split(r"\n(?=\[)", text):
        if not block.startswith("[unconnected_items]") and not block.startswith("[track_dangling]") \
                and not block.startswith("[via_dangling]"):
            continue
        items = []
        for line in block.splitlines()[1:]:
            if "@(" not in line:
                continue
            desc = line.split("): ", 1)[1]
            m = ITEM.search(desc)
            if m:
                items.append((desc.split()[0], m.group(1), m.group(2), m.group(3)))
        if not items:
            continue
        net = items[0][2]
        if net == "GND":
            fan += [f"{ref}:{num}" for kind, num, _n, ref in items if kind == "Pad"]
        elif all(kind == "Pad" for kind, *_ in items) and len(items) == 2 and net not in again:
            maze.append(f"{items[0][3]}:{items[0][1]}~{items[1][3]}:{items[1][1]}")
        elif not net.startswith("unconnected") and net not in rip:
            rip.append(net)
    print("MAZE " + " ".join(dict.fromkeys(maze)))
    print("RIP " + " ".join(rip))
    print("FAN " + " ".join(dict.fromkeys(fan)))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
