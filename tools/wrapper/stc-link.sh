#!/bin/sh
# Convert Arduino's .o/.a names back to SDCC .rel/.lib names and link.

SDCC="$1"
shift

STCXX_CPP_PROFILE=0
OUTPUT=""
EXPECT_OUTPUT=0
for ARGUMENT in "$@"; do
    if [ "$ARGUMENT" = "-DSTCXX_CPP_CORE=1" ]; then
        STCXX_CPP_PROFILE=1
    fi
    if [ "$EXPECT_OUTPUT" -eq 1 ]; then
        OUTPUT="$ARGUMENT"
        EXPECT_OUTPUT=0
    elif [ "$ARGUMENT" = "-o" ]; then
        EXPECT_OUTPUT=1
    fi
done

convert_stcxx_wsl_path() {
    STCXX_PATH_INPUT="$1"
    STCXX_PATH_ATTEMPT=1
    STCXX_PATH_STATUS=4
    while [ "$STCXX_PATH_ATTEMPT" -le 3 ]; do
        STCXX_PATH_CANDIDATE=$(wsl.exe -d "$WSL_DISTRIBUTION" -- \
            wslpath -a "$STCXX_PATH_INPUT")
        STCXX_PATH_STATUS=$?
        STCXX_PATH_CANDIDATE=$(printf '%s' "$STCXX_PATH_CANDIDATE" | \
            tr -d '\r')
        if [ "$STCXX_PATH_STATUS" -eq 0 ]; then
            case "$STCXX_PATH_CANDIDATE" in
                /*)
                    case "$STCXX_PATH_CANDIDATE" in
                        *'
'*) ;;
                        *)
                            printf '%s\n' "$STCXX_PATH_CANDIDATE"
                            return 0
                            ;;
                    esac
                    ;;
            esac
            STCXX_PATH_STATUS=4
        fi
        STCXX_PATH_ATTEMPT=$((STCXX_PATH_ATTEMPT + 1))
    done
    printf 'Unable to resolve an absolute WSL path after 3 attempts: %s\n' \
        "$STCXX_PATH_INPUT" >&2
    return "$STCXX_PATH_STATUS"
}

run_stcxx_wsl_cli() {
    STCXX_HANDSHAKE_MARKER="$1"
    STCXX_PIPELINE_READY_MARKER="$2"
    shift 2
    STCXX_LAUNCH_ATTEMPT=1
    STCXX_LAUNCH_STATUS=4
    while [ "$STCXX_LAUNCH_ATTEMPT" -le 3 ]; do
        rm -f "$STCXX_HANDSHAKE_MARKER" \
            "$STCXX_PIPELINE_READY_MARKER" || return 4
        # The standalone launcher creates the marker only after WSL has
        # started and validated the CLI.  The CLI creates the second marker
        # only after its tool/provenance preflight, immediately before the
        # actual linker pipeline.  Keeping inline shell source out of argv
        # avoids a second round of Windows BusyBox argument parsing.
        wsl.exe -d "$WSL_DISTRIBUTION" -- sh "$WSL_LAUNCHER_LINUX" \
            "$CLI_SCRIPT_LINUX" "$STCXX_HANDSHAKE_MARKER" \
            "$STCXX_PIPELINE_READY_MARKER" "$@"
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
            sleep "${STCXX_WSL_RETRY_DELAY_SECONDS:-1}"
        fi
    done
    return "$STCXX_LAUNCH_STATUS"
}

if [ "$STCXX_CPP_PROFILE" -eq 1 ]; then
    if [ -z "$OUTPUT" ]; then
        echo "C++ link recipe did not provide an output path" >&2
        exit 2
    fi
    WSL_DISTRIBUTION=${STCXX_WSL_DISTRO:-Ubuntu}
    WRAPPER_PATH=$(printf '%s\n' "$0" | tr '\\' '/')
    WRAPPER_DIRECTORY=${WRAPPER_PATH%/*}
    PLATFORM_TOOLS=${WRAPPER_DIRECTORY%/wrapper}
    CLI_SCRIPT_WINDOWS="$PLATFORM_TOOLS/cpp-cli/stcxx-cli.sh"
    CLI_SCRIPT_LINUX=$(convert_stcxx_wsl_path "$CLI_SCRIPT_WINDOWS") || exit $?
    case "$CLI_SCRIPT_LINUX" in
        */cpp-cli/stcxx-cli.sh)
            WSL_LAUNCHER_LINUX="${CLI_SCRIPT_LINUX%/cpp-cli/stcxx-cli.sh}/wrapper/stc-wsl-launch.sh"
            ;;
        *)
            printf 'Resolved C++ CLI path has an unexpected layout: %s\n' \
                "$CLI_SCRIPT_LINUX" >&2
            exit 4
            ;;
    esac
    OUTPUT_WINDOWS=$(printf '%s\n' "$OUTPUT" | tr '\\' '/')
    ARGUMENT_FILE="$OUTPUT_WINDOWS.stcxx-link-arguments-$$"
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
    HANDSHAKE_MARKER_WINDOWS=$(printf '%s\n' "$HANDSHAKE_MARKER" | tr '\\' '/')
    PIPELINE_READY_MARKER_WINDOWS=$(printf '%s\n' \
        "$PIPELINE_READY_MARKER" | tr '\\' '/')
    run_stcxx_wsl_cli "$HANDSHAKE_MARKER_WINDOWS" \
        "$PIPELINE_READY_MARKER_WINDOWS" \
        link - "$OUTPUT_WINDOWS" "$ARGUMENT_FILE"
    STATUS=$?
    if ! rm -f "$ARGUMENT_FILE" "$HANDSHAKE_MARKER" \
        "$PIPELINE_READY_MARKER"; then
        if [ "$STATUS" -eq 0 ]; then
            STATUS=4
        fi
    fi
    trap - 0 1 2 3 15
    exit "$STATUS"
fi

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
