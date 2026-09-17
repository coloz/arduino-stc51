# Unified STCXX toolchain packages

Arduino installs `stcxx-toolchain` and `stc-cli`. The toolchain layout is:

```text
stcxx-toolchain/
  MANIFEST.sha256
  toolchain.json
  frontend/    # Clang, LLVM-CBE, LLVM tools, headers, licenses, Windows Python
  sdcc/        # SDCC, assembler, linker, C headers, runtime libraries, licenses
```

The component builders remain in `stcxx/arduino/scripts/` and this repository's
`scripts/build-*-toolchain.sh`. Their component archives are build inputs, not
separate Arduino dependencies. `tools/toolchain-manifest.json` keeps these
source identities under `components`; only `tools` are installed.

From the `arduino-stc51` repository, first build or obtain the exact component
archives recorded in the native SDK locks. For each host, run the bundler
(Python 3.11+); substitute the actual archive filenames:

```powershell
python ../stcxx/arduino/scripts/package-toolchain.py --sdcc <windows-sdcc.zip> --frontend <windows-frontend.tar.bz2> --lock tools/cpp-cli/toolchain-lock.windows-x86_64.json --version 0.1.0 --output dist/release-0.0.5/assets
python ../stcxx/arduino/scripts/package-toolchain.py --sdcc <macos-sdcc.tar.bz2> --frontend <macos-frontend.tar.bz2> --lock tools/cpp-cli/toolchain-lock.macos-arm64.json --version 0.1.0 --output dist/release-0.0.5/assets
python scripts/finalize-toolchain.py --assets dist/release-0.0.5/assets --version 0.1.0
```

The bundler validates component archive hashes and complete file manifests,
preserves executable modes and internal file links, and writes a deterministic
archive plus a JSON report. It refuses to overwrite an existing output. It can
package either host on Windows without executing that host's compiler.
The finalizer validates both outputs, updates native bundle bindings and shared
adapter hashes, and updates the installable tool manifest. After changing a
component, update its source/SDK identity first, select a new toolchain version,
then rebuild and finalize both bundles.

Copy the two locked `stc-cli` archives into the same assets directory, then:

```powershell
./scripts/package-platform.ps1 -OutputDirectory dist/release-0.0.5/assets
python scripts/create-release-index.py --assets dist/release-0.0.5/assets --output dist/release-0.0.5/assets/package_arduino-stc51_candidate_index.json
python scripts/verify-release-assets.py dist/release-0.0.5/assets/package_arduino-stc51_candidate_index.json dist/release-0.0.5/assets
python scripts/check-native-install.py --assets dist/release-0.0.5/assets --work dist/release-0.0.5/native-windows --host windows --cli <arduino-cli.exe> --stc <stc-cli.exe>
```

On macOS run the same installation check with `--host macos`, native executable
paths and a fresh work directory. The check serves archives over loopback,
installs into isolated Arduino data, clears tool overrides, and exercises C/C++
compilation, linking, cache reuse and offline HEX validation. Packaging on
Windows alone does not validate execution on macOS. These commands do not publish
the release or change an existing Arduino installation.

For source builds, pass `-ToolCacheDirectory dist/release-0.0.5/assets` to
`scripts/build-example.ps1`. For direct adapter debugging, `STCXX_TOOLS_ROOT`
selects the extracted bundle root. The existing component overrides
`STCXX_CPP_TOOLS_ROOT` and `STCXX_SDCC` still select individual locked components.
