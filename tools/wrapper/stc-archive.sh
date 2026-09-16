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

# The C++ profile provides a board-sized override for SDCC's default 1 KiB
# heap.  Keep that object out of the core archive: ASlink diagnoses duplicate
# public symbols while indexing core.lib and libsdcc.lib even when it ultimately
# extracts only the override.  The C++ link wrapper validates this exact object
# and places it explicitly before core.lib.
case "$REL" in
    */stcxx_heap.c.rel|*\\stcxx_heap.c.rel|stcxx_heap.c.rel)
        case "$ARCHIVE" in
            */core.a|*\\core.a|core.a) ;;
            *)
                echo "Refusing to exclude STCXX heap from a non-core archive: $ARCHIVE" >&2
                exit 2
                ;;
        esac
        # If earlier members already created the archive, keep its Arduino and
        # SDCC names byte-identical.  If this is the first recipe invocation,
        # a later ordinary core member will create both files.
        if [ -f "$ARCHIVE" ]; then
            cp -f "$ARCHIVE" "${ARCHIVE%.a}.lib"
        fi
        exit 0
        ;;
esac

"$SDAR" "$@" "$ARCHIVE" "$REL" || exit $?
cp -f "$ARCHIVE" "${ARCHIVE%.a}.lib"
