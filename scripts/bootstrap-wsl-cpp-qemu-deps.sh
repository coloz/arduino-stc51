#!/usr/bin/env bash
# Install the host-side build dependencies used by the experimental C++
# toolchain and the MCS251 QEMU runner.  WSL installations behind a
# transparent proxy can make apt's parallel downloader unreliable, while a
# single HTTPS transfer remains reliable.  Ask apt for the exact package set,
# download each authenticated archive serially, then let apt install only from
# its cache.

set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "error: run this script as root (wsl.exe -u root -- ...)" >&2
  exit 2
fi

cpp_packages=(
  clang-20
  llvm-20
  llvm-20-dev
  llvm-20-tools
  lld-20
  cmake
  ninja-build
)

qemu_packages=(
  cmake
  ninja-build
  pkg-config
  meson
  python3-venv
  python3-wheel
  libglib2.0-dev
  libpixman-1-dev
  libfdt-dev
  zlib1g-dev
  flex
  bison
)

mode=${1:-all}
case "$mode" in
  cpp) packages=("${cpp_packages[@]}") ;;
  qemu) packages=("${qemu_packages[@]}") ;;
  all) packages=("${cpp_packages[@]}" "${qemu_packages[@]}") ;;
  *)
    echo "usage: $0 [all|cpp|qemu]" >&2
    exit 2
    ;;
esac

cache_dir=/var/cache/apt/archives
uri_list="$(mktemp --tmpdir stc-arduino-apt-uris.XXXXXX)"
trap 'rm -f "$uri_list"' EXIT

apt-get --print-uris -y --no-install-recommends install "${packages[@]}" \
  | awk '/^\047/ { print }' >"$uri_list"

download_one() {
  local quoted_url=$1
  local filename=$2
  local expected_size=$3
  local digest=$4
  local url=${quoted_url#\'}
  local destination
  local attempt

  url=${url%\'}
  url=${url/http:\/\/archive.ubuntu.com\/ubuntu\//https:\/\/mirrors.aliyun.com\/ubuntu\/}
  url=${url/http:\/\/security.ubuntu.com\/ubuntu\//https:\/\/mirrors.aliyun.com\/ubuntu\/}
  destination="$cache_dir/$filename"

  if [[ -f "$destination" ]] \
      && [[ "$(stat -c %s "$destination")" == "$expected_size" ]] \
      && echo "${digest#MD5Sum:}  $destination" | md5sum --check --status; then
    echo "cached: $filename"
    return
  fi

  rm -f "$destination"
  for attempt in 1 2 3 4 5; do
    echo "download ($attempt/5): $filename"
    if wget --quiet --show-progress --timeout=60 --tries=3 \
        --output-document="$destination" "$url" \
        && [[ "$(stat -c %s "$destination")" == "$expected_size" ]] \
        && echo "${digest#MD5Sum:}  $destination" | md5sum --check --status; then
      return
    fi
    rm -f "$destination"
  done

  echo "error: failed to download or verify $filename" >&2
  exit 3
}

while read -r quoted_url filename expected_size digest; do
  download_one "$quoted_url" "$filename" "$expected_size" "$digest"
done <"$uri_list"

DEBIAN_FRONTEND=noninteractive apt-get --no-download \
  --no-install-recommends -y install "${packages[@]}"

if [[ "$mode" != qemu ]]; then
  clang-20 --version | head -n 1
  llvm-config-20 --version
fi
cmake --version | head -n 1
ninja --version
