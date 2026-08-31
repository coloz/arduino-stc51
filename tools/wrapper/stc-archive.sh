#!/bin/sh
# Create the Arduino core archive with a separately pinned working sdar.

SDAR="$1"
ARCHIVE="$2"
OBJECT="$3"
shift 3

case "$OBJECT" in
    *.o) REL="${OBJECT%.o}.rel" ;;
    *) REL="$OBJECT" ;;
esac

if [ ! -f "$REL" ]; then
    echo "Core object not found: $REL" >&2
    exit 2
fi

"$SDAR" "$@" "$ARCHIVE" "$REL" || exit $?
cp -f "$ARCHIVE" "${ARCHIVE%.a}.lib"
