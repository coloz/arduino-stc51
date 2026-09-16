#!/bin/sh
# Link every Arduino build through the audited C++ driver.

SDCC="$1"
shift

OUTPUT=""
EXPECT_OUTPUT=0
for ARGUMENT in "$@"; do
    case "$ARGUMENT" in
        -mmcs51|-DSTCXX_TARGET_MCS51=1|-DSTC_EXECUTION_MODE_MCS51|-DSTC_EXECUTION_MODE_MCS51=*|-DSTC16F40K128)
            printf 'Target support has been removed; select a current MCS251 board.\n' >&2
            exit 2 ;;
    esac
    if [ "$EXPECT_OUTPUT" -eq 1 ]; then
        OUTPUT="$ARGUMENT"
        EXPECT_OUTPUT=0
    elif [ "$ARGUMENT" = "-o" ]; then
        EXPECT_OUTPUT=1
    fi
done

run_stcxx_native_cli() {
    STCXX_HANDSHAKE_MARKER="$1"
    STCXX_PIPELINE_READY_MARKER="$2"
    shift 2
    STCXX_LAUNCH_ATTEMPT=1
    STCXX_LAUNCH_STATUS=4
    while [ "$STCXX_LAUNCH_ATTEMPT" -le 3 ]; do
        rm -f "$STCXX_HANDSHAKE_MARKER" \
            "$STCXX_PIPELINE_READY_MARKER" || return 4
        # The standalone launcher creates the marker only after it has
        # started and validated the CLI.  The CLI creates the second marker
        # only after its tool/provenance preflight, immediately before the
        # actual linker pipeline.  Keeping inline shell source out of argv
        # preserves argument boundaries when starting the native driver.
        STCXX_ARDUINO_SDCC="$SDCC" sh "$NATIVE_LAUNCHER" "$CLI_SCRIPT_NATIVE" \
            "$STCXX_HANDSHAKE_MARKER" "$STCXX_PIPELINE_READY_MARKER" "$@"
        STCXX_LAUNCH_STATUS=$?
        if [ -f "$STCXX_PIPELINE_READY_MARKER" ]; then
            return "$STCXX_LAUNCH_STATUS"
        fi
        # Success without the CLI commit marker is not success: a truncated
        # or prematurely exiting driver must never satisfy Arduino Builder.
        if [ "$STCXX_LAUNCH_STATUS" -eq 0 ]; then
            STCXX_LAUNCH_STATUS=4
        fi
        STCXX_LAUNCH_ATTEMPT=$((STCXX_LAUNCH_ATTEMPT + 1))
        if [ "$STCXX_LAUNCH_ATTEMPT" -le 3 ]; then
            sleep "${STCXX_RETRY_DELAY_SECONDS:-1}"
        fi
    done
    return "$STCXX_LAUNCH_STATUS"
}

if [ -z "$OUTPUT" ]; then
    echo "C++ link recipe did not provide an output path" >&2
    exit 2
fi
WRAPPER_PATH=$(printf '%s\n' "$0" | tr '\\' '/')
WRAPPER_DIRECTORY=${WRAPPER_PATH%/*}
PLATFORM_TOOLS=${WRAPPER_DIRECTORY%/wrapper}
CLI_SCRIPT_INPUT="$PLATFORM_TOOLS/cpp-cli/stcxx-cli.sh"
case "$(uname -s)" in
    Darwin) . "$WRAPPER_DIRECTORY/stc-macos-env.sh" || exit $? ;;
    Linux) ;;
    *) printf 'Use the PowerShell adapter on Windows.\n' >&2; exit 2 ;;
esac
CLI_SCRIPT_NATIVE=$(realpath -e "$CLI_SCRIPT_INPUT") || exit $?
case "$CLI_SCRIPT_NATIVE" in
    */cpp-cli/stcxx-cli.sh)
        NATIVE_LAUNCHER="${CLI_SCRIPT_NATIVE%/cpp-cli/stcxx-cli.sh}/wrapper/stc-native-launch.sh"
        ;;
    *)
        printf 'Resolved C++ CLI path has an unexpected layout: %s\n' \
            "$CLI_SCRIPT_NATIVE" >&2
        exit 4
        ;;
esac
OUTPUT_INPUT=$(printf '%s\n' "$OUTPUT" | tr '\\' '/')
ARGUMENT_FILE="$OUTPUT_INPUT.stcxx-link-arguments-$$"
HANDSHAKE_MARKER="$ARGUMENT_FILE.stcxx-handshake"
PIPELINE_READY_MARKER="$ARGUMENT_FILE.stcxx-pipeline-ready"
rm -f "$ARGUMENT_FILE" "$HANDSHAKE_MARKER" \
    "$PIPELINE_READY_MARKER" || exit 4
trap 'rm -f "$ARGUMENT_FILE" "$HANDSHAKE_MARKER" "$PIPELINE_READY_MARKER"' 0
trap 'exit 130' 1 2 3 15
: > "$ARGUMENT_FILE" || exit 4
for ARGUMENT in "$@"; do
    printf '%s\0' "$ARGUMENT" >> "$ARGUMENT_FILE" || exit 4
done
HANDSHAKE_MARKER_INPUT=$(printf '%s\n' "$HANDSHAKE_MARKER" | tr '\\' '/')
PIPELINE_READY_MARKER_INPUT=$(printf '%s\n' \
    "$PIPELINE_READY_MARKER" | tr '\\' '/')
run_stcxx_native_cli "$HANDSHAKE_MARKER_INPUT" \
    "$PIPELINE_READY_MARKER_INPUT" \
    link - "$OUTPUT_INPUT" "$ARGUMENT_FILE"
STATUS=$?
if ! rm -f "$ARGUMENT_FILE" "$HANDSHAKE_MARKER" \
    "$PIPELINE_READY_MARKER"; then
    if [ "$STATUS" -eq 0 ]; then
        STATUS=4
    fi
fi
trap - 0 1 2 3 15
exit "$STATUS"
