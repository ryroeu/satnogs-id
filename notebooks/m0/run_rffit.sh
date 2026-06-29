#!/bin/bash
# Build the strf inputs, then drive the (interactive) rffit headless via Xvfb + xdotool:
# send 'i' (identify against the catalog) and 'q' (quit); capture stdout.
set -u
python /m0/make_dat.py || { echo "make_dat failed"; exit 1; }
echo "--------------------------------------------------------"
export ST_DATADIR=/opt/strf
export PGPLOT_DEV=/xw
Xvfb :99 -screen 0 1400x1000x24 >/tmp/xvfb.log 2>&1 &
sleep 2
export DISPLAY=:99
cd /data/strf
( rffit -d geoscan.dat -c soup.tle -s 9001 >/data/strf/rffit_out.log 2>&1 ) &
RFFIT=$!
sleep 4
WIN=$(xdotool search --name PGPLOT 2>/dev/null | head -1)
echo "PGPLOT window id: '${WIN:-<none>}'"
if [ -n "${WIN:-}" ]; then
  xdotool windowactivate --sync "$WIN" 2>/dev/null; sleep 1
  xdotool key --window "$WIN" i; sleep 5      # identify
  xdotool key --window "$WIN" q; sleep 1      # quit
else
  echo "no PGPLOT window. xvfb log:"; cat /tmp/xvfb.log
  echo "open windows:"; xdotool search --name '' 2>/dev/null | while read w; do echo "  $w $(xdotool getwindowname $w 2>/dev/null)"; done
fi
sleep 2
kill $RFFIT 2>/dev/null
echo "==================== rffit output ===================="
cat /data/strf/rffit_out.log
