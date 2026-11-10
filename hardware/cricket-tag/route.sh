#!/bin/sh
# Разводка cricket-tag с нуля: схема → плата → Freerouting → доводка → сшивка → DRC.
# Подробности в README платы, раздел «Разводка». Freerouting от запуска к запуску даёт
# разное: порядок деталей в DSN зависит от их UUID.
# Доводку выбирает autofix.py по отчёту DRC, так что она подстраивается под результат.
#
#   sh route.sh            # TMP — папка для промежуточных файлов, по умолчанию /tmp/cricket-route
set -e
cd "$(dirname "$0")"
TMP=${TMP:-/tmp/cricket-route}; mkdir -p "$TMP"
KICAD_PY=${KICAD_PY:-/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3}
JAVA=${JAVA:-/opt/homebrew/opt/openjdk/bin/java}          # Freerouting 2.5 требует Java 25+
FREEROUTING=${FREEROUTING:?путь к freerouting-2.5.0.jar}
q() { grep -v "memory leak\|GetWidth\|image handler" || true; }

kicad-cli sch export netlist cricket-tag.kicad_sch -o "$TMP/cricket.net" >/dev/null
$KICAD_PY gen_pcb.py "$TMP/cricket.net" 2>&1 | q
$KICAD_PY export_dsn.py "$TMP/cricket-tag.dsn" 2>&1 | q   # GND разводится дорожками, без --planes (D-29)
"$JAVA" -jar "$FREEROUTING" -de "$TMP/cricket-tag.dsn" -do "$TMP/cricket-tag.ses" -mp 150 \
  --gui.enabled=false --usage_and_diagnostic_data.disable_analytics=true --api_server.enabled=false \
  > "$TMP/freerouting.log" 2>&1
grep -o "final score: [0-9.]* ([0-9]* unrouted[^)]*)" "$TMP/freerouting.log" | tail -1
$KICAD_PY import_ses.py "$TMP/cricket-tag.ses" 2>&1 | q
while [ "$($KICAD_PY cleanup.py 2>/dev/null | tail -1)" != 0 ]; do :; done
# доводка того, что Freerouting оставил (D-28): по отчёту DRC, до четырёх кругов
$KICAD_PY connect.py repair 2>&1 | q
AGAIN=""
for i in 1 2 3 4; do
  kicad-cli pcb drc cricket-tag.kicad_pcb -o "$TMP/drc0.rpt" >/dev/null 2>&1 || true
  python3 autofix.py "$TMP/drc0.rpt" $AGAIN > "$TMP/fix.txt"
  MAZE=$(sed -n 's/^MAZE //p' "$TMP/fix.txt"); RIP=$(sed -n 's/^RIP //p' "$TMP/fix.txt"); FAN=$(sed -n 's/^FAN //p' "$TMP/fix.txt")
  [ -z "$MAZE$RIP$FAN" ] && break
  echo "круг $i: maze [$MAZE] заново [$RIP] gnd [$FAN]"
  [ -n "$RIP" ] && $KICAD_PY ripup.py $RIP 2>&1 | q >/dev/null
  NETS=""; for n in $RIP; do NETS="$NETS NET:$n"; done
  [ -n "$MAZE$NETS" ] && $KICAD_PY maze.py $MAZE $NETS 2>&1 | q | grep -v "проложено" | tee "$TMP/maze.txt" || true
  # цепи, которые не легли парой площадок, на следующем круге снимаются целиком
  AGAIN=$(sed -n 's/^\([^:]*\):\([^~]*\)~.*пути нет.*/\1:\2/p' "$TMP/maze.txt" | while read p; do
    $KICAD_PY -c "import sys; sys.path.insert(0, '.'); import pcbnew, fanout; b = pcbnew.LoadBoard('cricket-tag.kicad_pcb'); print(fanout.find_pad(b, '$p').GetNetname())" 2>/dev/null | tail -1; done | sort -u | tr '\n' ' ')
  [ -n "$FAN" ] && $KICAD_PY fanout.py $FAN 2>&1 | q || true
done
$KICAD_PY widen.py 2>&1 | q >/dev/null
$KICAD_PY stitch.py 2>&1 | q
while [ "$($KICAD_PY cleanup.py --gnd-vias 2>/dev/null | tail -1)" != 0 ]; do :; done
kicad-cli pcb drc cricket-tag.kicad_pcb -o "$TMP/drc.rpt" >/dev/null 2>&1 || true
grep "Found" "$TMP/drc.rpt"
