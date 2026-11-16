# Shared helpers, sourced by the other scripts. BusyBox ash compatible.
DIR=$(cd "$(dirname "$0")" && pwd)
. "$DIR/settings.conf"
IMG="$DIR/screen.png"
NEW="$DIR/screen.new.png"
VIEW="${VIEW:-today}"
n=0

# Old BusyBox od may lack -t; fall back to -d (unsigned 16-bit decimal).
if echo ab | od -An -t d2 >/dev/null 2>&1; then ODFMT="-t d2"; else ODFMT="-d"; fi

log() { echo "$(date +%H:%M:%S) $*" >> "$DIR/dashboard.log"; }

batt() {
  b=$(lipc-get-prop com.lab126.powerd battLevel 2>/dev/null)
  case "$b" in ''|*[!0-9]*) b=$(powerd_test -s 2>/dev/null | sed -n 's/.*[Bb]attery [Ll]evel: *\([0-9]*\).*/\1/p' | head -n 1);; esac
  case "$b" in ''|*[!0-9]*) echo "";; *) echo "$b";; esac
}

# dl URL OUTFILE: download with the configured tool(s). Returns 0 if OUTFILE is non-empty.
dl() {
  rm -f "$2"
  case "$FETCHER" in
    curl) _tools="curl" ;;
    wget) _tools="wget" ;;
    *)    _tools="wget curl" ;;
  esac
  for _t in $_tools; do
    case "$_t" in
      wget) wget -q -T 20 -O "$2" "$1" 2>/dev/null ;;
      curl) command -v curl >/dev/null 2>&1 || continue
            if [ "$CURL_INSECURE" = 1 ]; then curl -s -k -L -m 30 -o "$2" "$1" 2>/dev/null
            else curl -s -L -m 30 -o "$2" "$1" 2>/dev/null; fi ;;
    esac
    [ -s "$2" ] && return 0
    log "$_t failed for $1"
  done
  rm -f "$2"
  return 1
}

# Get the picture for the current $VIEW into $NEW. Returns 0 if we got something.
fetch() {
  case "$URL" in
    /*)      rm -f "$NEW"; cp "$URL" "$NEW" 2>/dev/null ;;
    *.png)   b=$(batt); dl "$URL?view=$VIEW&rot=$ROT${b:+&batt=$b}" "$NEW" ;;
    *)       dl "${URL%/}/$VIEW.png" "$NEW" ;;
  esac
  [ -s "$NEW" ]
}

# Show $IMG. Every FULL_EVERY-th draw is a full flash refresh.
draw() {
  n=$((n + 1))
  if [ "$FULL_EVERY" -gt 0 ] && [ $((n % FULL_EVERY)) -eq 0 ]; then
    eips -f -g "$IMG" >/dev/null 2>&1
  else
    eips -g "$IMG" >/dev/null 2>&1
  fi
}

freeze() {
  [ "$FREEZE_UI" = 1 ] || return 0
  lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
  killall -STOP cvm 2>/dev/null
}

thaw() {
  lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null
  [ "$FREEZE_UI" = 1 ] || return 0
  killall -CONT cvm 2>/dev/null
  if [ "$RESTORE" = restart ]; then /etc/init.d/framework restart >/dev/null 2>&1; fi
}

# Read hardware button presses and leave a request in $DIR/req ("stop" or "toggle").
watch_keys() {
  [ -r "$KEYDEV" ] || { log "no key device $KEYDEV, buttons disabled"; return; }
  bad=0
  while :; do
    set -- $(dd if="$KEYDEV" bs=16 count=1 2>/dev/null | od -An $ODFMT)
    # fields: sec_lo sec_hi usec_lo usec_hi type code value_lo value_hi
    if [ -z "$5" ]; then
      bad=$((bad + 1)); [ "$bad" -gt 20 ] && return; sleep 1; continue
    fi
    [ "$5" = 1 ] && [ "$7" = 1 ] || continue      # key-down events only
    case " $HOME_KEYS " in *" $6 "*) echo stop > "$DIR/req";; esac
    case " $NEXT_KEYS " in *" $6 "*) echo toggle > "$DIR/req";; esac
  done
}
