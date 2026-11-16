#!/bin/sh
DIR=$(cd "$(dirname "$0")" && pwd)
if [ -f "$DIR/loop.pid" ] && kill -0 "$(cat "$DIR/loop.pid")" 2>/dev/null; then exit 0; fi
sh "$DIR/loop.sh" >/dev/null 2>&1 &
