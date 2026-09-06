#!/bin/sh
# Adapt Arduino's GCC-like invocation to SDCC's plain-C frontend.

SDCC="$1"
SOURCE="$2"
OBJECT="$3"
MARK="$4"
shift 4

STCXX_CPP_PROFILE=0
for ARGUMENT in "$@"; do
    if [ "$ARGUMENT" = "-DSTCXX_CPP_CORE=1" ]; then
        STCXX_CPP_PROFILE=1
        break
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
        # actual compiler pipeline.  Keeping inline shell source out of argv
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

run_stcxx_wsl() {
    MODE="$1"
    shift
    WSL_DISTRIBUTION=${STCXX_WSL_DISTRO:-Ubuntu}
    WRAPPER_PATH=$(printf '%s\n' "$0" | tr '\\' '/')
    WRAPPER_DIRECTORY=${WRAPPER_PATH%/*}
    PLATFORM_TOOLS=${WRAPPER_DIRECTORY%/wrapper}
    CLI_SCRIPT_WINDOWS="$PLATFORM_TOOLS/cpp-cli/stcxx-cli.sh"
    CLI_SCRIPT_LINUX=$(convert_stcxx_wsl_path "$CLI_SCRIPT_WINDOWS") || return $?
    case "$CLI_SCRIPT_LINUX" in
        */cpp-cli/stcxx-cli.sh)
            WSL_LAUNCHER_LINUX="${CLI_SCRIPT_LINUX%/cpp-cli/stcxx-cli.sh}/wrapper/stc-wsl-launch.sh"
            ;;
        *)
            printf 'Resolved C++ CLI path has an unexpected layout: %s\n' \
                "$CLI_SCRIPT_LINUX" >&2
            return 4
            ;;
    esac

    SOURCE_WINDOWS=$(printf '%s\n' "$SOURCE" | tr '\\' '/')
    OBJECT_WINDOWS=$(printf '%s\n' "$OBJECT" | tr '\\' '/')
    case "$OBJECT_WINDOWS" in
        [Nn][Uu][Ll]|[Nn][Uu][Ll]:|/dev/null)
            TEMP_WINDOWS=$(printf '%s\n' "${TEMP:-.}" | tr '\\' '/')
            ARGUMENT_FILE="$TEMP_WINDOWS/stcxx-arguments-$$"
            ;;
        *) ARGUMENT_FILE="$OBJECT_WINDOWS.stcxx-arguments-$$" ;;
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
    ARGUMENT_FILE_WINDOWS=$(printf '%s\n' "$ARGUMENT_FILE" | tr '\\' '/')
    HANDSHAKE_MARKER_WINDOWS=$(printf '%s\n' "$HANDSHAKE_MARKER" | tr '\\' '/')
    PIPELINE_READY_MARKER_WINDOWS=$(printf '%s\n' \
        "$PIPELINE_READY_MARKER" | tr '\\' '/')
    run_stcxx_wsl_cli "$HANDSHAKE_MARKER_WINDOWS" \
        "$PIPELINE_READY_MARKER_WINDOWS" \
        "$MODE" "$SOURCE_WINDOWS" "$OBJECT_WINDOWS" "$ARGUMENT_FILE_WINDOWS"
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

if [ "$STCXX_CPP_PROFILE" -eq 1 ]; then
    case "$MARK:$SOURCE" in
        re11:*.cpp|re11:*.cpp.merged)
            run_stcxx_wsl preprocess-deps "$@"
            exit $?
            ;;
        re12:*.cpp|re12:*.cpp.merged)
            run_stcxx_wsl preprocess-macros "$@"
            exit $?
            ;;
        re2:*.cpp|re2:*.cpp.merged)
            run_stcxx_wsl compile-cpp "$@"
            exit $?
            ;;
        re1:*.c)
            run_stcxx_wsl compile-c "$@"
            exit $?
            ;;
    esac
fi

# ash resolves a Windows executable without its suffix, but BusyBox xargs does
# not. Arduino's tool property intentionally uses the cross-platform name
# "sdcc", so normalize it once before either execution path is selected.
if [ ! -f "$SDCC" ] && [ -f "$SDCC.exe" ]; then
    SDCC="$SDCC.exe"
fi

# Arduino captures dependency discovery from stdout and passes the host null
# device as the nominal output path. Do not forward it to SDCC; on Windows the
# compiler otherwise creates a repository-local file named nul.d.
if [ "$MARK" = "re11" ]; then
    "$SDCC" "$@" -x c "$SOURCE"
    exit $?
fi

# Arduino runs the macro/dependency probe for both generated sketches and
# library C sources.  The host null device is the nominal macro output.  SDCC
# ignores GCC's -MF destination and, if passed "nul" via -o on Windows, leaks
# a real repository-local file named nul.d.  Handle this before dispatching on
# the source extension so .c, .cpp, and .cpp.merged all follow the safe path.
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
                *.cpp.merged) DEPENDENCY_NAME=${SOURCE_NAME%.merged}.d ;;
                *.cpp) DEPENDENCY_NAME=${SOURCE_NAME%.cpp}.d ;;
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
                # misread as compiler input files. macOS xargs and the Windows
                # BusyBox xargs applet implement -0.
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

case "$SOURCE" in
    *.cpp|*.cpp.merged)
        if [ "$MARK" = "re12" ]; then
            "$SDCC" "$@" -x c "$SOURCE" -o "$OBJECT"
        else
            "$SDCC" "$@" -x c --include dummy_variable_main.h "$SOURCE" -o "$OBJECT"
        fi
        STATUS=$?
        ;;
    *.c)
        "$SDCC" "$@" "$SOURCE" -o "$OBJECT"
        STATUS=$?
        ;;
    *)
        echo "Unsupported source extension: $SOURCE" >&2
        exit 2
        ;;
esac

if [ "$STATUS" -ne 0 ] || [ "$MARK" = "re12" ]; then
    exit "$STATUS"
fi

# Arduino tracks .o files; the SDCC linker and sdar traditionally use .rel.
case "$OBJECT" in
    *.o)
        REL="${OBJECT%.o}.rel"
        if [ -f "$OBJECT" ]; then
            cp -f "$OBJECT" "$REL"
        elif [ -f "$REL" ]; then
            cp -f "$REL" "$OBJECT"
        else
            echo "SDCC produced neither $OBJECT nor $REL" >&2
            exit 3
        fi
        ;;
esac

exit 0
