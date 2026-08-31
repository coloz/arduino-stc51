#!/bin/sh
set -eu

ARCH=${1:-}
OUTPUT_DIRECTORY=${2:-}

case "$ARCH" in
    arm64|x86_64) ;;
    *) echo "usage: $0 <arm64|x86_64> <output-directory>" >&2; exit 2 ;;
esac

if [ -z "$OUTPUT_DIRECTORY" ]; then
    echo "usage: $0 <arm64|x86_64> <output-directory>" >&2
    exit 2
fi

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This toolchain package must be built on macOS." >&2
    exit 2
fi

if ! command -v brew >/dev/null 2>&1 || ! brew --prefix boost >/dev/null 2>&1 ||
   [ ! -d "$(brew --prefix boost)/include/boost" ]; then
    echo "Missing Boost headers. Install the Homebrew boost formula first." >&2
    exit 2
fi

TAG=v4.6.0-mcs251-20260804
COMMIT=b09075b6a93e6afe10645181e3aeff041ea37f87
ARCHIVE_NAME="sdcc-mcs251-macos-$ARCH-$COMMIT.tar.bz2"
WORK_DIRECTORY=$(mktemp -d /tmp/arduino-stc51-toolchain.XXXXXX)

cleanup() {
    case "$WORK_DIRECTORY" in
        /tmp/arduino-stc51-toolchain.*) rm -rf "$WORK_DIRECTORY" ;;
        *) echo "Refusing to clean unexpected path: $WORK_DIRECTORY" >&2 ;;
    esac
}
trap cleanup EXIT HUP INT TERM

git clone --depth 1 --branch "$TAG" https://github.com/gevico/sdcc-c251.git "$WORK_DIRECTORY/source"
ACTUAL_COMMIT=$(git -C "$WORK_DIRECTORY/source" rev-parse HEAD)
if [ "$ACTUAL_COMMIT" != "$COMMIT" ]; then
    echo "Source commit mismatch: $ACTUAL_COMMIT" >&2
    exit 3
fi

mkdir -p "$WORK_DIRECTORY/build"
cd "$WORK_DIRECTORY/build"

CFLAGS="-std=gnu17 -O2 -arch $ARCH" \
CXXFLAGS="-O2 -arch $ARCH" \
CPPFLAGS="-I$(brew --prefix boost)/include" \
LDFLAGS="-arch $ARCH" \
../source/configure \
    --enable-mcs251-port \
    --prefix=/sdcc-mcs251 \
    --datarootdir=/sdcc-mcs251 \
    'docdir=${datarootdir}/doc' \
    include_dir_suffix=include \
    non_free_include_dir_suffix=non-free/include \
    lib_dir_suffix=lib \
    non_free_lib_dir_suffix=non-free/lib \
    --disable-z80-port \
    --disable-z180-port \
    --disable-r2k-port \
    --disable-r2ka-port \
    --disable-r3ka-port \
    --disable-r4k-port \
    --disable-r5k-port \
    --disable-r6k-port \
    --disable-sm83-port \
    --disable-tlcs90-port \
    --disable-ez80-port \
    --disable-z80n-port \
    --disable-r800-port \
    --disable-ds390-port \
    --disable-ds400-port \
    --disable-pic14-port \
    --disable-pic16-port \
    --disable-hc08-port \
    --disable-s08-port \
    --disable-stm8-port \
    --disable-pdk13-port \
    --disable-pdk14-port \
    --disable-pdk15-port \
    --disable-mos6502-port \
    --disable-mos65c02-port \
    --disable-f8-port \
    --disable-f8l-port \
    --disable-ucsim \
    --disable-sdcdb \
    --disable-non-free

make -j"$(sysctl -n hw.logicalcpu)"
make DESTDIR="$WORK_DIRECTORY/stage" install

PACKAGE_ROOT="$WORK_DIRECTORY/stage/sdcc-mcs251"
cp "$WORK_DIRECTORY/source/README.md" "$WORK_DIRECTORY/source/COPYING" "$PACKAGE_ROOT/"
cp "$WORK_DIRECTORY/source/sdas/COPYING3" "$PACKAGE_ROOT/"

if ! file "$PACKAGE_ROOT/bin/sdcc" | grep -q "$ARCH"; then
    echo "Packaged compiler architecture is not $ARCH." >&2
    exit 4
fi
if ! "$PACKAGE_ROOT/bin/sdcc" --version | grep -q 'mcs51/mcs251'; then
    echo "Packaged compiler does not expose both target ports." >&2
    exit 4
fi
if find "$PACKAGE_ROOT/bin" -type f -maxdepth 1 -print0 |
   xargs -0 file | grep 'Mach-O' | cut -d: -f1 |
   while IFS= read -r executable; do otool -L "$executable"; done |
   grep -E '/opt/homebrew|/usr/local'; then
    echo "Packaged executables retain a non-system Homebrew dependency." >&2
    exit 4
fi

find "$PACKAGE_ROOT" -exec touch -h -t 202608310000 {} +
mkdir -p "$OUTPUT_DIRECTORY"
COPYFILE_DISABLE=1 tar -cjf "$OUTPUT_DIRECTORY/$ARCHIVE_NAME" \
    -C "$WORK_DIRECTORY/stage" sdcc-mcs251

stat -f 'size=%z' "$OUTPUT_DIRECTORY/$ARCHIVE_NAME"
printf 'sha256='
shasum -a 256 "$OUTPUT_DIRECTORY/$ARCHIVE_NAME" | awk '{print $1}'
