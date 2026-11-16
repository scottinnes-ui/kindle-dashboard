#!/bin/sh
# Safe first test: fetch one frame, show it for 20 s, then give the Kindle UI back.
. "$(dirname "$0")/lib.sh"
lipc-set-prop com.lab126.wifid enable 1 2>/dev/null
if fetch; then
  mv -f "$NEW" "$IMG"
  freeze; FULL_EVERY=1; draw
  sleep 20
else
  freeze; eips -c >/dev/null 2>&1
  eips 2 20 "Could not fetch the picture."
  eips 2 22 "Check URL in settings.conf and that"
  eips 2 23 "the PC server is running."
  sleep 12
fi
thaw
