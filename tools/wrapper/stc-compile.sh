#!/bin/sh
# Adapt Arduino's GCC-like invocation to SDCC's plain-C frontend.

SDCC="$1"
SOURCE="$2"
OBJECT="$3"
MARK="$4"
shift 4

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
