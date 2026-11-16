#!/bin/sh
# Shows on screen whether this Kindle can download the picture over HTTPS (wget / curl / curl -k).
. "$(dirname "$0")/lib.sh"
lipc-set-prop com.lab126.wifid enable 1 2>/dev/null
case "$URL" in *.png) T="$URL" ;; *) T="${URL%/}/today.png" ;; esac
T1="$DIR/t1.tmp"; T2="$DIR/t2.tmp"; T3="$DIR/t3.tmp"
rm -f "$T1" "$T2" "$T3"
wget -q -T 20 -O "$T1" "$T" 2>/dev/null
if command -v curl >/dev/null 2>&1; then
  curl -s -L -m 30 -o "$T2" "$T" 2>/dev/null
  curl -s -k -L -m 30 -o "$T3" "$T" 2>/dev/null
fi
r() { if [ -s "$1" ]; then echo OK; else echo FAIL; fi; }
freeze; eips -c >/dev/null 2>&1
eips 2 2  "Download test: $T"
eips 2 5  "wget          : $(r $T1)"
eips 2 6  "curl          : $(r $T2)"
eips 2 7  "curl -k       : $(r $T3)"
eips 2 9  "curl installed: $(command -v curl >/dev/null 2>&1 && echo yes || echo no)"
eips 2 12 "OK on any line = that method works."
eips 2 13 "Set FETCHER / CURL_INSECURE in settings.conf."
sleep 20
rm -f "$T1" "$T2" "$T3"
thaw
