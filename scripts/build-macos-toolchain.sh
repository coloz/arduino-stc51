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

SCRIPT_DIRECTORY=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
REPOSITORY_ROOT=$(CDPATH= cd -- "$SCRIPT_DIRECTORY/.." && pwd -P)

case "$OUTPUT_DIRECTORY" in
    /*) ;;
    *) OUTPUT_DIRECTORY="$(pwd -P)/$OUTPUT_DIRECTORY" ;;
esac

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This toolchain package must be built on macOS." >&2
    exit 2
fi

for dependency in git make file grep lipo otool vtool gtar shasum; do
    if ! command -v "$dependency" >/dev/null 2>&1; then
        echo "Missing build dependency: $dependency" >&2
        exit 2
    fi
done

if ! command -v brew >/dev/null 2>&1 || ! brew --prefix boost >/dev/null 2>&1 ||
   [ ! -d "$(brew --prefix boost)/include/boost" ]; then
    echo "Missing Boost headers. Install the Homebrew boost formula first." >&2
    exit 2
fi

TAG=v4.6.0-mcs251-20260804
COMMIT=b09075b6a93e6afe10645181e3aeff041ea37f87
SOURCE_REPOSITORY=${SDCC_SOURCE_REPOSITORY:-https://github.com/gevico/sdcc-c251.git}
PACKAGE_REVISION=3
PATCH_PATH="$REPOSITORY_ROOT/tools/toolchain-patches/sdcc-mcs251-arduino-cpp.patch"
PATCH_SHA256=fcb1342a77a412dbb8b0c8c6e8e4df5e1b59744790e63e40c32dd812c9472e12
PATCHED_GEN_BLOB=c77304895fc568bfcf095d2b4668671e18971ad4
MINIMUM_MACOS_VERSION=11.0
ARCHIVE_NAME="sdcc-mcs251-macos-$ARCH-$COMMIT-r$PACKAGE_REVISION.tar.bz2"
WORK_DIRECTORY="/tmp/arduino-stc51-toolchain-build-$ARCH"
SOURCE_DATE_EPOCH=1788134400
LC_ALL=C
TZ=UTC
MACOSX_DEPLOYMENT_TARGET=$MINIMUM_MACOS_VERSION
export SOURCE_DATE_EPOCH LC_ALL TZ MACOSX_DEPLOYMENT_TARGET

if [ ! -f "$PATCH_PATH" ]; then
    echo "Missing locked source patch: $PATCH_PATH" >&2
    exit 2
fi
ACTUAL_PATCH_SHA256=$(shasum -a 256 "$PATCH_PATH" | awk '{print $1}')
if [ "$ACTUAL_PATCH_SHA256" != "$PATCH_SHA256" ]; then
    echo "MCS251 patch SHA-256 mismatch: $ACTUAL_PATCH_SHA256" >&2
    exit 3
fi

cleanup() {
    case "$WORK_DIRECTORY" in
        /tmp/arduino-stc51-toolchain-build-arm64|/tmp/arduino-stc51-toolchain-build-x86_64)
            rm -rf "$WORK_DIRECTORY"
            ;;
        *) echo "Refusing to clean unexpected path: $WORK_DIRECTORY" >&2 ;;
    esac
}

if [ -e "$WORK_DIRECTORY" ] || [ -L "$WORK_DIRECTORY" ]; then
    echo "Refusing to reuse an existing deterministic build directory: $WORK_DIRECTORY" >&2
    exit 3
fi
umask 077
mkdir "$WORK_DIRECTORY"
trap cleanup EXIT HUP INT TERM

CLONE_ATTEMPT=1
while ! git -c http.version=HTTP/1.1 -c http.lowSpeedLimit=1024 \
    -c http.lowSpeedTime=60 clone --depth 1 --branch "$TAG" \
    "$SOURCE_REPOSITORY" "$WORK_DIRECTORY/source"; do
    if [ "$CLONE_ATTEMPT" -ge 4 ]; then
        echo "Source clone failed after $CLONE_ATTEMPT attempts." >&2
        exit 3
    fi
    rm -rf "$WORK_DIRECTORY/source"
    CLONE_ATTEMPT=$((CLONE_ATTEMPT + 1))
    echo "Source clone failed; retrying ($CLONE_ATTEMPT/4)..." >&2
done
ACTUAL_COMMIT=$(git -C "$WORK_DIRECTORY/source" rev-parse HEAD)
if [ "$ACTUAL_COMMIT" != "$COMMIT" ]; then
    echo "Source commit mismatch: $ACTUAL_COMMIT" >&2
    exit 3
fi

# Apply the same locked patch and source gates as the Linux build.
# A host package must not be produced from the upstream tag alone.
git -C "$WORK_DIRECTORY/source" apply --check "$PATCH_PATH"
git -C "$WORK_DIRECTORY/source" apply "$PATCH_PATH"
git -C "$WORK_DIRECTORY/source" apply --reverse --check "$PATCH_PATH"
git -C "$WORK_DIRECTORY/source" diff --check
ACTUAL_PATCHED_GEN_BLOB=$(git -C "$WORK_DIRECTORY/source" hash-object src/mcs251/gen.c)
if [ "$ACTUAL_PATCHED_GEN_BLOB" != "$PATCHED_GEN_BLOB" ]; then
    echo "Patched MCS251 gen.c blob mismatch: $ACTUAL_PATCHED_GEN_BLOB" >&2
    exit 3
fi

mkdir -p "$WORK_DIRECTORY/build"
cd "$WORK_DIRECTORY/build"

CFLAGS="-std=gnu17 -O2 -arch $ARCH -mmacosx-version-min=$MINIMUM_MACOS_VERSION -ffile-prefix-map=$WORK_DIRECTORY=." \
CXXFLAGS="-O2 -arch $ARCH -mmacosx-version-min=$MINIMUM_MACOS_VERSION -ffile-prefix-map=$WORK_DIRECTORY=." \
CPPFLAGS="-I$(brew --prefix boost)/include" \
LDFLAGS="-arch $ARCH -mmacosx-version-min=$MINIMUM_MACOS_VERSION -Wl,-no_uuid" \
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

# Upstream device-library rules share temporary assembler files across models;
# a parallel build can race while copying/removing those files.
make -j1

make DESTDIR="$WORK_DIRECTORY/stage" install

PACKAGE_ROOT="$WORK_DIRECTORY/stage/sdcc-mcs251"
cp "$WORK_DIRECTORY/source/README.md" "$WORK_DIRECTORY/source/COPYING" "$PACKAGE_ROOT/"
cp "$WORK_DIRECTORY/source/sdas/COPYING3" "$PACKAGE_ROOT/"
cp "$PATCH_PATH" "$PACKAGE_ROOT/"

# These installed host-development artifacts are not used by SDCC at runtime.
# They contain build-directory strings or archive metadata, so exclude them
# from the redistributable runtime package.
find "$PACKAGE_ROOT/lib" -maxdepth 1 -type f \( -name '*.a' -o -name '*.la' \) -delete
rm -rf "$PACKAGE_ROOT/lib/src"

if ! "$PACKAGE_ROOT/bin/sdcc" --version | grep -q 'mcs51/mcs251'; then
    echo "Packaged compiler does not expose both target ports." >&2
    exit 4
fi
MACHO_LIST="$WORK_DIRECTORY/macho-files.txt"
find "$PACKAGE_ROOT" -type f -exec file {} \; |
    awk -F: '$2 ~ /Mach-O/ { print $1 }' > "$MACHO_LIST"
if [ ! -s "$MACHO_LIST" ]; then
    echo "Package contains no Mach-O executables." >&2
    exit 4
fi
while IFS= read -r executable; do
    EXECUTABLE_ARCHS=$(lipo -archs "$executable")
    if [ "$EXECUTABLE_ARCHS" != "$ARCH" ]; then
        echo "Packaged executable architecture is '$EXECUTABLE_ARCHS', expected '$ARCH': $executable" >&2
        exit 4
    fi
    if ! vtool -show-build "$executable" |
         grep -Eq "minos[[:space:]]+$MINIMUM_MACOS_VERSION([.]0)*$"; then
        echo "Packaged executable has the wrong deployment target: $executable" >&2
        vtool -show-build "$executable" >&2
        exit 4
    fi
    if otool -l "$executable" | grep -q 'cmd LC_RPATH'; then
        echo "Packaged executable retains LC_RPATH: $executable" >&2
        exit 4
    fi
    otool -L "$executable" | tail -n +2 | awk '{ print $1 }' |
        while IFS= read -r dependency; do
            case "$dependency" in
                /usr/lib/*|/System/Library/*) ;;
                *)
                    echo "Packaged executable has a non-system dependency: $executable -> $dependency" >&2
                    exit 4
                    ;;
            esac
        done
done < "$MACHO_LIST"

mkdir -p "$OUTPUT_DIRECTORY"
COPYFILE_DISABLE=1 gtar --sort=name --mtime="@$SOURCE_DATE_EPOCH" \
    --owner=0 --group=0 --numeric-owner --format=gnu \
    -cjf "$OUTPUT_DIRECTORY/$ARCHIVE_NAME" \
    -C "$WORK_DIRECTORY/stage" sdcc-mcs251

stat -f 'size=%z' "$OUTPUT_DIRECTORY/$ARCHIVE_NAME"
printf 'sha256='
shasum -a 256 "$OUTPUT_DIRECTORY/$ARCHIVE_NAME" | awk '{print $1}'
