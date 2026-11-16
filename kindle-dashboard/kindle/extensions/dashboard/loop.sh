#!/bin/sh
# Main loop: fetch picture from the PC -> redraw if changed -> wait -> repeat.
. "$(dirname "$0")/lib.sh"
: > "$DIR/dashboard.log"
echo $$ > "$DIR/loop.pid"
rm -f "$DIR/req"
fails=0; banner=0; KPID=""

cleanup() {
  trap - EXIT INT TERM
  [ -n "$KPID" ] && kill "$KPID" 2>/dev/null
  rm -f "$DIR/loop.pid" "$DIR/req"
  log "stopping"
  thaw
  exit 0
}
trap cleanup EXIT INT TERM

lipc-set-prop com.lab126.wifid enable 1 2>/dev/null
freeze
watch_keys &
KPID=$!
log "started, url=$URL interval=$INTERVAL"

while :; do
  if fetch; then
    fails=0
    if [ "$banner" = 1 ]; then rm -f "$IMG"; banner=0; fi
    if ! cmp -s "$NEW" "$IMG" 2>/dev/null; then
      mv -f "$NEW" "$IMG"; draw; log "drawn view=$VIEW"
    else
      rm -f "$NEW"; log "unchanged"
    fi
  else
    fails=$((fails + 1)); log "fetch failed ($fails)"
    if [ "$fails" -ge 3 ]; then
      banner=1
      eips 1 48 "Offline - retrying (check Wi-Fi and the PC server)" >/dev/null 2>&1
    fi
  fi

  t=0
  while [ "$t" -lt "$INTERVAL" ]; do
    sleep 2; t=$((t + 2))
    if [ -f "$DIR/req" ]; then
      r=$(cat "$DIR/req" 2>/dev/null); rm -f "$DIR/req"
      case "$r" in
        stop) exit 0 ;;
        toggle) if [ "$VIEW" = today ]; then VIEW=10d; else VIEW=today; fi
                rm -f "$IMG"; break ;;
      esac
    fi
  done
done
