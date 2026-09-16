#!/bin/sh
# Start the native POSIX C++ driver and report successful preflight.
if [ "$#" -lt 4 ]; then
    exit 126
fi

CLI_SCRIPT="$1"
HANDSHAKE_INPUT="$2"
PIPELINE_READY_INPUT="$3"
shift 3

case "$CLI_SCRIPT" in
    /*) ;;
    *) exit 126 ;;
esac
[ -f "$CLI_SCRIPT" ] && [ -r "$CLI_SCRIPT" ] || exit 126

to_native_path() {
    realpath -m -- "$1"
}

HANDSHAKE_NATIVE=$(to_native_path "$HANDSHAKE_INPUT") || exit 126
HANDSHAKE_NATIVE=$(printf '%s' "$HANDSHAKE_NATIVE" | tr -d '\r')
case "$HANDSHAKE_NATIVE" in
    /*) ;;
    *) exit 126 ;;
esac
case "$HANDSHAKE_NATIVE" in
    *'
'*) exit 126 ;;
esac

: > "$HANDSHAKE_NATIVE" || exit 126
[ -f "$HANDSHAKE_NATIVE" ] || exit 126

PIPELINE_READY_NATIVE=$(to_native_path "$PIPELINE_READY_INPUT") || exit 126
PIPELINE_READY_NATIVE=$(printf '%s' "$PIPELINE_READY_NATIVE" | tr -d '\r')
case "$PIPELINE_READY_NATIVE" in
    /*) ;;
    *) exit 126 ;;
esac
case "$PIPELINE_READY_NATIVE" in
    *'
'*) exit 126 ;;
esac

rm -f "$PIPELINE_READY_NATIVE" || exit 126
export STCXX_PIPELINE_READY_MARKER="$PIPELINE_READY_NATIVE"
exec "${STCXX_BASH:-bash}" "$CLI_SCRIPT" "$@"
