#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
  echo "usage: verify-standalone-release.sh OUT_DIR EXPECTED_MANIFEST_SHA256 EXPECTED_LOCK_SHA256" >&2
  exit 2
fi

out_dir=$1
expected_manifest_sha=$2
expected_lock_sha=$3

case "${out_dir}" in
  /*) ;;
  *) echo "standalone release OUT_DIR must be absolute" >&2; exit 2 ;;
esac
printf '%s\n' "${expected_manifest_sha}" | grep -Eq '^[0-9a-f]{64}$' || {
  echo "expected standalone manifest SHA-256 is malformed" >&2
  exit 2
}
printf '%s\n' "${expected_lock_sha}" | grep -Eq '^[0-9a-f]{64}$' || {
  echo "expected standalone lock SHA-256 is malformed" >&2
  exit 2
}

resolved_out=$(CDPATH= cd -- "${out_dir}" 2>/dev/null && pwd -P) || {
  echo "standalone release OUT_DIR does not exist" >&2
  exit 2
}
[ "${resolved_out}" != "/" ] || {
  echo "standalone release OUT_DIR cannot be the filesystem root" >&2
  exit 2
}
manifest=${resolved_out}/MANIFEST.sha256
published_lock=${resolved_out}/toolchain-lock.json
[ -f "${manifest}" ] || {
  echo "standalone release manifest is missing" >&2
  exit 2
}
[ -f "${published_lock}" ] || {
  echo "standalone release lock is missing" >&2
  exit 2
}

observed_manifest_sha=$(sha256sum "${manifest}" | awk '{print $1}')
[ "${observed_manifest_sha}" = "${expected_manifest_sha}" ] || {
  echo "standalone release manifest SHA-256 mismatch" >&2
  exit 2
}
observed_lock_sha=$(sha256sum "${published_lock}" | awk '{print $1}')
[ "${observed_lock_sha}" = "${expected_lock_sha}" ] || {
  echo "standalone release lock SHA-256 mismatch" >&2
  exit 2
}

file_count=$(awk 'NF { count++ } END { print count + 0 }' "${manifest}")
[ "${file_count}" -gt 0 ] || {
  echo "standalone release manifest is empty" >&2
  exit 2
}
(
  cd "${resolved_out}"
  sha256sum --quiet -c MANIFEST.sha256
)

printf 'STANDALONE_RELEASE_FILE_COUNT=%s\n' "${file_count}"
printf 'STANDALONE_RELEASE_MANIFEST=PASS\n'
