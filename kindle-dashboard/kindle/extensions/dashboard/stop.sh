#!/bin/sh
. "$(dirname "$0")/lib.sh"
if [ -f "$DIR/loop.pid" ] && kill -0 "$(cat "$DIR/loop.pid")" 2>/dev/null; then
  kill "$(cat "$DIR/loop.pid")"      # loop.sh's trap restores the Kindle UI
else
  rm -f "$DIR/loop.pid"; thaw
fi
