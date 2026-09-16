#!/bin/sh
# Dispatch Arduino compilation to the C++ driver and its C hardware backend.

SDCC="$1"
SOURCE="$2"
OBJECT="$3"
MARK="$4"
shift 4

for ARGUMENT in "$@"; do
    case "$ARGUMENT" in
        -mmcs51|-DSTCXX_TARGET_MCS51=1|-DSTC_EXECUTION_MODE_MCS51|-DSTC_EXECUTION_MODE_MCS51=*|-DSTC16F40K128)
            printf 'Target support has been removed; select a current MCS251 board.\n' >&2
            exit 2 ;;
    esac
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
        # actual compiler pipeline.  Keeping inline shell source out of argv
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

run_stcxx_native() {
    MODE="$1"
    shift
    WRAPPER_PATH=$(printf '%s\n' "$0" | tr '\\' '/')
    WRAPPER_DIRECTORY=${WRAPPER_PATH%/*}
    PLATFORM_TOOLS=${WRAPPER_DIRECTORY%/wrapper}
    CLI_SCRIPT_INPUT="$PLATFORM_TOOLS/cpp-cli/stcxx-cli.sh"
    case "$(uname -s)" in
        Darwin) . "$WRAPPER_DIRECTORY/stc-macos-env.sh" || return $? ;;
        Linux) ;;
        *) printf 'Use the PowerShell adapter on Windows.\n' >&2; return 2 ;;
    esac
    CLI_SCRIPT_NATIVE=$(realpath -e "$CLI_SCRIPT_INPUT") || return $?
    case "$CLI_SCRIPT_NATIVE" in
        */cpp-cli/stcxx-cli.sh)
            NATIVE_LAUNCHER="${CLI_SCRIPT_NATIVE%/cpp-cli/stcxx-cli.sh}/wrapper/stc-native-launch.sh"
            ;;
        *)
            printf 'Resolved C++ CLI path has an unexpected layout: %s\n' \
                "$CLI_SCRIPT_NATIVE" >&2
            return 4
            ;;
    esac

    SOURCE_INPUT=$(printf '%s\n' "$SOURCE" | tr '\\' '/')
    OBJECT_INPUT=$(printf '%s\n' "$OBJECT" | tr '\\' '/')
    case "$OBJECT_INPUT" in
        [Nn][Uu][Ll]|[Nn][Uu][Ll]:|/dev/null)
            TEMP_INPUT=$(printf '%s\n' "${TEMP:-.}" | tr '\\' '/')
            ARGUMENT_FILE="$TEMP_INPUT/stcxx-arguments-$$"
            ;;
        *) ARGUMENT_FILE="$OBJECT_INPUT.stcxx-arguments-$$" ;;
    esac

    HANDSHAKE_MARKER="$ARGUMENT_FILE.stcxx-handshake"
    PIPELINE_READY_MARKER="$ARGUMENT_FILE.stcxx-pipeline-ready"
    rm -f "$ARGUMENT_FILE" "$HANDSHAKE_MARKER" \
        "$PIPELINE_READY_MARKER" || return 4
    trap 'rm -f "$ARGUMENT_FILE" "$HANDSHAKE_MARKER" "$PIPELINE_READY_MARKER"' 0
    trap 'exit 130' 1 2 3 15
    : > "$ARGUMENT_FILE" || return 4
    for ARGUMENT in "$@"; do
        printf '%s\0' "$ARGUMENT" >> "$ARGUMENT_FILE" || return 4
    done
    ARGUMENT_FILE_INPUT=$(printf '%s\n' "$ARGUMENT_FILE" | tr '\\' '/')
    HANDSHAKE_MARKER_INPUT=$(printf '%s\n' "$HANDSHAKE_MARKER" | tr '\\' '/')
    PIPELINE_READY_MARKER_INPUT=$(printf '%s\n' \
        "$PIPELINE_READY_MARKER" | tr '\\' '/')
    run_stcxx_native_cli "$HANDSHAKE_MARKER_INPUT" \
        "$PIPELINE_READY_MARKER_INPUT" \
        "$MODE" "$SOURCE_INPUT" "$OBJECT_INPUT" "$ARGUMENT_FILE_INPUT"
    STATUS=$?
    if ! rm -f "$ARGUMENT_FILE" "$HANDSHAKE_MARKER" \
        "$PIPELINE_READY_MARKER"; then
        if [ "$STATUS" -eq 0 ]; then
            STATUS=4
        fi
    fi
    trap - 0 1 2 3 15
    return "$STATUS"
}

case "$MARK:$SOURCE" in
    re11:*.cpp|re11:*.cpp.merged)
        run_stcxx_native preprocess-deps "$@"
        exit $?
        ;;
    re12:*.cpp|re12:*.cpp.merged)
        run_stcxx_native preprocess-macros "$@"
        exit $?
        ;;
    re2:*.cpp|re2:*.cpp.merged)
        run_stcxx_native compile-cpp "$@"
        exit $?
        ;;
    re1:*.c)
        run_stcxx_native compile-c "$@"
        exit $?
        ;;
esac

# The only direct SDCC calls are dependency probes for internal C sources.
case "$MARK:$SOURCE" in
    re11:*.c|re12:*.c) ;;
    *) printf 'Unsupported compile input: %s %s\n' "$MARK" "$SOURCE" >&2; exit 2 ;;
esac

# Arduino captures dependency discovery from stdout and passes the host null
# device as the nominal output path. Do not forward it to SDCC; on Windows the
# compiler otherwise creates a repository-local file named nul.d.
if [ "$MARK" = "re11" ]; then
    "$SDCC" "$@" -x c "$SOURCE"
    exit $?
fi

# Internal C library probes use the host null device as nominal output. SDCC
# ignores GCC's -MF destination and, if passed "nul" via -o on Windows, leaks
# a real repository-local file named nul.d, so handle the output separately.
if [ "$MARK" = "re12" ]; then
    case "$OBJECT" in
        [Nn][Uu][Ll]|[Nn][Uu][Ll]:|/dev/null)
            MF_PATH=""
            CAPTURE_MF_PATH=0
            for ARGUMENT in "$@"; do
                if [ "$CAPTURE_MF_PATH" -eq 1 ]; then
                    if [ -n "$MF_PATH" ]; then
                        MF_PATH="$MF_PATH $ARGUMENT"
                    else
                        MF_PATH="$ARGUMENT"
                    fi
                elif [ "$ARGUMENT" = "-MF" ]; then
                    # Arduino CLI appends -MF without shell quoting. If the
                    # build path contains spaces, the wrapper sees the rest of
                    # that path as separate arguments.
                    CAPTURE_MF_PATH=1
                fi
            done

            SOURCE_POSIX=$(printf '%s\n' "$SOURCE" | tr '\\' '/')
            SOURCE_NAME=${SOURCE_POSIX##*/}
            case "$SOURCE_NAME" in
                *.c) DEPENDENCY_NAME=${SOURCE_NAME%.c}.d ;;
                *)
                    echo "Unsupported discovery source: $SOURCE" >&2
                    exit 2
                    ;;
            esac

            if [ -n "$MF_PATH" ]; then
                MF_POSIX=$(printf '%s\n' "$MF_PATH" | tr '\\' '/')
                WORK_DIRECTORY=${MF_POSIX%/*}
            else
                MF_POSIX=""
                WORK_DIRECTORY=${SOURCE_POSIX%/*}
            fi

            (
                cd "$WORK_DIRECTORY" || exit 4
                # Keep every original argument before -MF, preventing
                # fragments of Arduino's unquoted dependency path from being
                # misread as compiler input files. Native xargs accepts -0.
                ARGUMENT_FILE=".stc-sdcc-arguments-$$"
                : > "$ARGUMENT_FILE" || exit 4
                for ARGUMENT in "$@"; do
                    if [ "$ARGUMENT" = "-MF" ]; then
                        break
                    fi
                    printf '%s\0' "$ARGUMENT" >> "$ARGUMENT_FILE"
                done
                printf '%s\0' -x c "$SOURCE" >> "$ARGUMENT_FILE"
                xargs -0 "$SDCC" < "$ARGUMENT_FILE"
                DISCOVERY_STATUS=$?
                rm -f "$ARGUMENT_FILE"
                if [ "$DISCOVERY_STATUS" -eq 0 ] && [ -n "$MF_POSIX" ]; then
                    if [ -f "$DEPENDENCY_NAME" ]; then
                        mv -f "$DEPENDENCY_NAME" "$MF_POSIX" || exit 5
                    elif [ ! -f "$MF_POSIX" ]; then
                        echo "SDCC did not produce the Arduino dependency file" >&2
                        exit 5
                    fi
                fi
                exit "$DISCOVERY_STATUS"
            )
            exit $?
            ;;
    esac
fi

"$SDCC" "$@" -x c "$SOURCE" -o "$OBJECT"
