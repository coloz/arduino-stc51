#!/bin/sh
# Enter the locked Linux C++ pipeline without passing shell source through the
# Windows command-line parser.  The caller uses the marker to distinguish a
# WSL startup failure from a real compiler or linker failure.

if [ "$#" -lt 4 ]; then
    exit 126
fi

CLI_SCRIPT="$1"
HANDSHAKE_WINDOWS="$2"
PIPELINE_READY_WINDOWS="$3"
shift 3

case "$CLI_SCRIPT" in
    /*) ;;
    *) exit 126 ;;
esac
[ -f "$CLI_SCRIPT" ] && [ -r "$CLI_SCRIPT" ] || exit 126

HANDSHAKE_LINUX=$(wslpath -a "$HANDSHAKE_WINDOWS") || exit 126
HANDSHAKE_LINUX=$(printf '%s' "$HANDSHAKE_LINUX" | tr -d '\r')
case "$HANDSHAKE_LINUX" in
    /*) ;;
    *) exit 126 ;;
esac
case "$HANDSHAKE_LINUX" in
    *'
'*) exit 126 ;;
esac

: > "$HANDSHAKE_LINUX" || exit 126
[ -f "$HANDSHAKE_LINUX" ] || exit 126

PIPELINE_READY_LINUX=$(wslpath -a "$PIPELINE_READY_WINDOWS") || exit 126
PIPELINE_READY_LINUX=$(printf '%s' "$PIPELINE_READY_LINUX" | tr -d '\r')
case "$PIPELINE_READY_LINUX" in
    /*) ;;
    *) exit 126 ;;
esac
case "$PIPELINE_READY_LINUX" in
    *'
'*) exit 126 ;;
esac

rm -f "$PIPELINE_READY_LINUX" || exit 126
export STCXX_PIPELINE_READY_MARKER="$PIPELINE_READY_LINUX"
exec bash "$CLI_SCRIPT" "$@"
