# Release artifacts

Current release: [v0.0.2](https://github.com/coloz/arduino-stc51/releases/tag/v0.0.2).

New binary archives are stored as immutable GitHub Release assets. The Boards Manager index pins their exact sizes and SHA-256 values. Do not overwrite published assets; use a new version for byte changes. `release-manifest.json` at the repository root describes the complete release asset set, including corresponding source and the independent stc-cli packages.

The historical 0.0.1 platform and unpatched macOS archives remain here because the preserved 0.0.1 index references them. They are not the current toolchain. Fresh patched Linux and macOS packages have the `-r1` suffix and versioned v0.0.2 URLs.

See [release qualification](../docs/releases/0.0.2.md) for the 92 plain-C build results and the limited Windows/WSL C++ smoke checks. macOS Intel is executed using Rosetta; no physical hardware qualification is claimed.
