#!/bin/sh
# Sourced only for native Mac C++ builds. Homebrew dependencies are explicit
# because Arduino launched from Finder does not inherit a terminal's PATH.
if [ "$(uname -m)" != arm64 ]; then
    echo 'The native Mac C++ frontend currently requires ARM64.' >&2
    return 2
fi
STCXX_BASH=${STCXX_BASH:-/opt/homebrew/opt/bash/bin/bash}
STCXX_COREUTILS_BIN=${STCXX_COREUTILS_BIN:-/opt/homebrew/opt/coreutils/libexec/gnubin}
if ! [ -x "$STCXX_BASH" ] || ! [ -x "$STCXX_COREUTILS_BIN/realpath" ] ||
   ! [ -x "$STCXX_COREUTILS_BIN/sha256sum" ]; then
    echo 'Mac C++ builds require Bash 4.4+ and GNU coreutils; install bash and coreutils or set STCXX_BASH and STCXX_COREUTILS_BIN.' >&2
    return 2
fi
PATH="$STCXX_COREUTILS_BIN:/opt/homebrew/bin:$PATH"
export PATH STCXX_BASH
"$STCXX_BASH" -c '(( BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 4) ))' || {
    echo 'Mac C++ builds require Bash 4.4 or newer.' >&2
    return 2
}
command -v python3 >/dev/null || {
    echo 'Mac C++ builds require Python 3.' >&2
    return 2
}
