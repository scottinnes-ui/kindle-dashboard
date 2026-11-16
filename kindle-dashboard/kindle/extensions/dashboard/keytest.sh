#!/bin/sh
# Shows the raw input events on screen so you can find your buttons' key codes.
. "$(dirname "$0")/lib.sh"
freeze
eips -c >/dev/null 2>&1
eips 2 2 "Key test on $KEYDEV - press buttons"
i=0; bad=0
while [ "$i" -lt 24 ]; do
  set -- $(dd if="$KEYDEV" bs=16 count=1 2>/dev/null | od -An $ODFMT)
  if [ -z "$5" ]; then
    bad=$((bad + 1))
    if [ "$bad" -gt 5 ]; then eips 2 6 "Cannot read $KEYDEV - try event1/event2"; break; fi
    sleep 1; continue
  fi
  eips 2 $((4 + i)) "type=$5 code=$6 value=$7          "
  i=$((i + 1))
done
sleep 8
thaw
