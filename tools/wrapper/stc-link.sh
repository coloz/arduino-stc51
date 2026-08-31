#!/bin/sh
# Convert Arduino's .o/.a names back to SDCC .rel/.lib names and link.

SDCC="$1"
shift

# A TAB separator preserves spaces in paths while remaining compatible with
# BusyBox ash, dash and bash (no arrays or non-POSIX [[ ... ]] syntax).
TAB="$(printf '\tX')"
TAB="${TAB%X}"
LINE=""

for ARG do
    case "$ARG" in
        *.o) ARG="${ARG%.o}.rel" ;;
        *.a)
            LIB="${ARG%.a}.lib"
            if [ ! -f "$LIB" ]; then
                cp -f "$ARG" "$LIB" || exit $?
            fi
            ARG="$LIB"
            ;;
    esac
    if [ -z "$LINE" ]; then
        LINE="$ARG"
    else
        LINE="$LINE$TAB$ARG"
    fi
done

OLD_IFS="$IFS"
IFS="$TAB"
set -- $LINE
IFS="$OLD_IFS"
"$SDCC" "$@"
