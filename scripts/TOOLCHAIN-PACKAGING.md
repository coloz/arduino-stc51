# Native STCXX packages

Build the native driver with Rust and Node (Node is only a maintenance tool):

```text
node scripts/build-native-driver.mjs
tools/stcxx-driver/stcxx.exe package-platform . dist/arduino-stc51-native.zip
tools/stcxx-driver/stcxx.exe package-toolchain <existing-toolchain-root> dist/stcxx-toolchain-native.zip
```

The existing toolchain root supplies the locked Clang/LLVM-CBE and SDCC binaries.
The native packager includes only frontend/bin, frontend/lib, sdcc/bin,
sdcc/include, sdcc/lib, native libexec helpers and the corresponding license notices. It does not run
or package the old embedded interpreter, scripts, bytecode or build-input trees.
The platform includes the native driver, its dependency licenses, lock files,
core, variants, libraries and examples. Arduino invokes stcxx directly.

This SDK consumes prebuilt compiler packages. Compiler source patches, source
rebuild scripts and their dedicated notices are not SDK build inputs and have
been removed. Compiler development belongs to the separate `stcxx` project;
the host locks retain binary, ABI and source digest bindings. Packaging an
existing toolchain still includes the component licenses from that toolchain.

Archives use stable entry order and timestamps. Each ZIP has an adjacent JSON
report containing its size and SHA-256, and includes a file manifest. Existing
output ZIPs are never overwritten. Windows binaries statically link the C runtime.

The 0.0.6 Boards Manager release supplies Windows x64 and Apple Silicon native
packages with stcxx-toolchain 0.2.0 and stc-cli 0.1.0-stc.2. The index retains
0.0.5 and its original dependencies for rollback. Qualify a native build on Apple Silicon
before including that host in a release; Windows verification does not qualify macOS.
The obsolete driver wrappers, lock finalizers and their helper tests have been
removed. The candidate/release index scripts and `check-native-install.py` still
inspect the previous published archive format; they do not consume local legacy
driver sources and are not part of the native build or release procedure.

For native releases, package the platform as `arduino-stc51-<version>.zip`,
record tool archive sizes, hashes, roots and pinned release URLs in
`tools/toolchain-manifest.json`, then run:

```text
python scripts/create-native-release-index.py --platform dist/release-0.0.6/arduino-stc51-0.0.6.zip --assets dist/release-0.0.6 --previous dist/release-0.0.6/previous-index.json --output package_arduino-stc51_index.json
```

Save the published index as `previous-index.json` before generating the new one.
The native index generator verifies every ZIP payload manifest and tool archive
binding, requires matching host dependencies and driver binaries, and retains
previous versions. Uploader ZIPs include licenses, `MANIFEST.sha256` and a
`build-info.json` recording the source commit; publish a source snapshot alongside
the uploader. Validate installation with Arduino CLI in a separate data directory,
then use `qualify-release.py` and `check-upload.py` against that installation.
No packaging or index command publishes a GitHub release automatically.

To prepare an unpacked native compiler payload:

```text
tools/stcxx-driver/stcxx.exe stage-toolchain <existing-toolchain-root> <new-directory>
```

After extracting and validating a platform ZIP, the Windows local installer can
replace an existing published installation. Both arguments are unpacked directories:

```text
node scripts/install-native-driver.mjs <native-platform-directory> <native-toolchain-directory>
```

The installer retains the previous platform and toolchain under a unique
Arduino15-native-backups directory beside Arduino15 and records the paths in
installation.json. The existing 0.0.5 platform and 0.1.0 tool paths are retained
for this local override. Reinstalling from Boards Manager restores published
payloads, so do not confuse this local candidate with a published release.

For source validation use scripts/check-native-driver.mjs. The optional older
scripts/build-example.ps1 maintenance entry point delegates packaging to the
native driver and stages only native compiler components. It is not called by
Arduino recipes. See tools/stcxx-driver/README.md for driver details.
