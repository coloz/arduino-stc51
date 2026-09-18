use crate::util::*;
use anyhow::{Context, Result, bail, ensure};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
};

pub struct Driver {
    pub platform: PathBuf,
    pub source: PathBuf,
    pub output: Option<PathBuf>,
    pub mode: String,
    pub arguments: Vec<String>,
    pub lock: Value,
    pub frontend: PathBuf,
    pub sdcc: PathBuf,
    pub assembler: PathBuf,
    pub includes: PathBuf,
    pub runtime: PathBuf,
    pub triple: String,
    pub layout: String,
    pub abi: String,
    pub clang_args: Vec<String>,
    pub sdcc_args: Vec<String>,
    pub sections: Vec<String>,
    pub dependency: Option<PathBuf>,
    pub optimization: String,
    pub stack: BTreeMap<String, String>,
    pub clock: String,
    pub constrained: bool,
}
impl Driver {
    pub fn new(
        platform: PathBuf,
        sdcc: &str,
        source: &str,
        output: &str,
        mark: &str,
        arguments: Vec<String>,
    ) -> Result<Self> {
        let mode = match (mark, source.ends_with(".c")) {
            ("re1", true) => "compile-c",
            ("re2", false) => "compile-cpp",
            ("re11", _) => "preprocess-deps",
            ("re12", _) => "preprocess-macros",
            ("link", _) => "link",
            _ => bail!("unsupported compile input: {mark} {source}"),
        };
        if mode != "link" {
            ensure!(
                source.ends_with(".c")
                    || source.ends_with(".cpp")
                    || source.ends_with(".cpp.merged"),
                "unsupported source: {source}"
            );
            nonempty(source)?;
        }
        let sdcc = std::env::var("STCXX_SDCC").unwrap_or(sdcc.into());
        let sdcc = absolute(if Path::new(&sdcc).is_file() {
            sdcc
        } else {
            sdcc + std::env::consts::EXE_SUFFIX
        })?;
        let sdcc_root = sdcc
            .parent()
            .and_then(Path::parent)
            .context("invalid SDCC path")?;
        let package = std::env::var_os("STCXX_TOOLS_ROOT")
            .map(PathBuf::from)
            .unwrap_or(
                sdcc_root
                    .parent()
                    .context("missing package root")?
                    .to_path_buf(),
            );
        let frontend = std::env::var_os("STCXX_CPP_TOOLS_ROOT")
            .map(PathBuf::from)
            .unwrap_or(package.join("frontend"));
        let lock = json(platform.join(if cfg!(windows) {
            "tools/stcxx-driver/toolchain-lock.windows-x86_64.json"
        } else {
            "tools/stcxx-driver/toolchain-lock.macos-arm64.json"
        }))?;
        let target = &lock["targets"]["mcs251"];
        let mut d = Self {
            platform,
            source: absolute(source)?,
            output: if ["nul", "nul:", "/dev/null"].contains(&output.to_lowercase().as_str()) {
                None
            } else {
                Some(absolute(output)?)
            },
            mode: mode.into(),
            arguments,
            frontend,
            assembler: exe(&sdcc_root.join("bin"), "sdas251"),
            includes: sdcc_root.join("include"),
            runtime: sdcc_root.join("lib/mcs251-large-stack-auto"),
            triple: string(&target["target_triple"])?.into(),
            layout: string(&target["data_layout"])?.into(),
            abi: string(&target["abi_identity_symbol"])?.into(),
            sdcc,
            lock,
            clang_args: Vec::new(),
            sdcc_args: Vec::new(),
            sections: Vec::new(),
            dependency: None,
            optimization: "0".into(),
            stack: BTreeMap::new(),
            clock: String::new(),
            constrained: false,
        };
        d.parse()?;
        Ok(d)
    }
    fn parse(&mut self) -> Result<()> {
        let mut opt_count = 0;
        let mut clock_count = 0;
        let mut constrained_count = 0;
        let mut cpp = false;
        let mut target = false;
        let mut args = self.arguments.iter();
        while let Some(a) = args.next() {
            if a == "-MF" {
                let rest = args.by_ref().cloned().collect::<Vec<_>>();
                ensure!(!rest.is_empty(), "missing -MF destination");
                self.dependency = Some(absolute(rest.join(" "))?);
                break;
            }
            if a == "-DSTCXX_CPP_OPT" || a.starts_with("-DSTCXX_CPP_OPT=") {
                opt_count += 1;
                self.optimization = a.split_once('=').map(|p| p.1).unwrap_or("").into();
                ensure!(
                    opt_count == 1
                        && ["0", "1", "2", "s", "z"].contains(&self.optimization.as_str()),
                    "invalid STCXX_CPP_OPT"
                );
                continue;
            }
            ensure!(
                !["-mmcs51", "-DSTCXX_TARGET_MCS51=1", "-DSTC16F40K128"].contains(&a.as_str())
                    && !a.starts_with("-DSTC_EXECUTION_MODE_MCS51"),
                "MCS51 target has been removed"
            );
            if let Some(kv) = a.strip_prefix("-DSTCXX_MCS251_")
                && let Some((key, value)) = kv.split_once('=')
                && ["IRAM_SIZE", "STACK_LOC", "STACK_SIZE"].contains(&key)
            {
                ensure!(
                    self.stack.insert(key.into(), value.into()).is_none(),
                    "duplicate stack setting"
                );
                continue;
            }
            if a.starts_with("-DSTCXX_MCS251_CONSTRAINED_HEAP=") {
                ensure!(a.ends_with("=1"), "invalid constrained heap");
                self.constrained = true;
                constrained_count += 1;
            }
            if let Some(value) = a.strip_prefix("-DF_CPU=") {
                clock_count += 1;
                self.clock = value.trim_end_matches(['U', 'L']).into();
            }
            if a == "-mmcs251" {
                target = true;
                self.sdcc_args.push(a.clone());
            } else if a == "-Ddouble=float" {
            } else if a.starts_with("-D") {
                cpp |= a == "-DSTCXX_CPP_CORE=1";
                self.clang_args.push(a.clone());
                self.sdcc_args.push(a.clone());
            } else if let Some(include) = a.strip_prefix("-I") {
                let p = absolute(include)?;
                let value = format!("-I{}", s(&p));
                if !p.starts_with(&self.includes) {
                    self.clang_args.push(value.clone());
                }
                self.sdcc_args.push(value);
            } else if ["--function-sections", "--data-sections"].contains(&a.as_str()) {
                self.sections.push(a.clone());
                self.sdcc_args.push(a.clone());
            } else if [
                "-c",
                "--std-sdcc11",
                "--opt-code-size",
                "--less-pedantic",
                "--stack-auto",
                "--model-large",
                "-MMD",
                "-Wp-Wall",
                "-V",
            ]
            .contains(&a.as_str())
            {
                self.sdcc_args.push(a.clone());
            } else if ["-M", "-MG", "-MP", "-E", "-dM"].contains(&a.as_str()) {
            } else if self.mode == "compile-c" {
                self.sdcc_args.push(a.clone());
            } else if self.mode != "link" {
                bail!("unsupported Arduino compiler argument: {a}");
            }
        }
        ensure!(cpp && target, "MCS251 C++ profile is required");
        ensure!(
            clock_count == 1
                && (self.clock == "12000000"
                    || self.clock == "40000000"
                        && self.arguments.contains(&"-DAI8051U_34K64".into())
                    || self.clock == "48000000"
                        && self.arguments.contains(&"-DSTC32G144K246".into())),
            "unsupported C++ clock/profile"
        );
        ensure!(
            constrained_count <= 1,
            "duplicate constrained heap identity"
        );
        for flag in [
            "-DSTCXX_TARGET_ABI=1",
            "-DSTCXX_TARGET_MCS251=1",
            "-DSTCXX_TARGET_ENDIAN_LITTLE=0",
            "-DSTCXX_TARGET_ENDIAN_BIG=1",
        ] {
            self.clang_args.push(flag.into());
            self.sdcc_args.push(flag.into());
        }
        if self.mode == "link" {
            ensure!(self.stack.len() == 3, "missing extended stack layout");
            for v in self.stack.values() {
                ensure!(
                    v.starts_with("0x") && u32::from_str_radix(&v[2..], 16).is_ok(),
                    "invalid stack layout"
                );
            }
        }
        Ok(())
    }
    pub fn tool(&self, name: &str) -> PathBuf {
        exe(&self.frontend.join("bin"), name)
    }
    pub fn call(&self, name: &str, args: &[String], capture: bool) -> Result<Vec<u8>> {
        run(&self.tool(name), args, None, capture, None)
    }
    pub fn verify(&self) -> Result<()> {
        if let Some(files) = self.lock["frontend_files"].as_object() {
            for (name, expected) in files {
                safe_relative(name)?;
                check_hash(self.frontend.join(name), string(expected)?)?;
            }
        } else if let Some(expected) = self.lock["frontend_manifest_sha256"].as_str() {
            let manifest = self.frontend.join("SOURCE-MANIFEST.sha256");
            let manifest = if manifest.is_file() {
                manifest
            } else {
                self.frontend.join("MANIFEST.sha256")
            };
            check_hash(&manifest, expected)?;
            for line in text(&manifest)?.lines() {
                let (hash, name) = line.split_once("  ").context("invalid frontend manifest")?;
                safe_relative(name)?;
                if name.starts_with("bin/") || name.starts_with("lib/") {
                    check_hash(self.frontend.join(name), hash)?;
                }
            }
        }
        for name in ["clang", "llvm-link", "opt", "llvm-dis", "llvm-cbe"] {
            check_hash(
                self.tool(name),
                string(&self.lock["tools"][name.replace('-', "_")]["sha256"])?,
            )?;
        }
        let root = self.sdcc.parent().unwrap().parent().unwrap();
        for name in ["sdcc", "sdar", "sdas251", "sdld", "sdldmcs251", "sdcpp"] {
            check_hash(
                exe(&root.join("bin"), name),
                string(&self.lock["tools"][name]["sha256"])?,
            )?;
        }
        if let Some(files) = self
            .lock
            .get("sdcc_files")
            .unwrap_or(&self.lock["windows_sdcc_files"])
            .as_object()
        {
            for (name, expected) in files {
                safe_relative(name)?;
                check_hash(root.join(name), string(expected)?)?;
            }
        }
        for (name, key) in [("stddef.h", "stddef_sha256"), ("stdint.h", "stdint_sha256")] {
            check_hash(
                self.includes.join(name),
                string(&self.lock["tools"]["sdcc_inputs"][key])?,
            )?;
        }
        for (name, key) in [
            ("libsdcc.lib", "libsdcc_sha256"),
            ("mcs251.lib", "target_runtime_sha256"),
        ] {
            check_hash(
                self.runtime.join(name),
                string(&self.lock["targets"]["mcs251"]["sdcc_inputs"][key])?,
            )?;
        }
        Ok(())
    }
    pub fn clang_base(&self) -> Result<Vec<String>> {
        let resource =
            String::from_utf8(self.call("clang", &["--print-resource-dir".into()], true)?)?;
        let resource = PathBuf::from(resource.trim());
        let headers = self.platform.join("cores/STC/cpp");
        ensure!(
            resource.join("include").is_dir() && headers.is_dir(),
            "missing C++ headers"
        );
        let mut args = vec![
            format!("--target={}", self.triple),
            "-x".into(),
            "c++".into(),
            "-std=gnu++11".into(),
            format!("-O{}", self.optimization),
        ];
        args.extend(
            [
                "-fno-vectorize",
                "-fno-slp-vectorize",
                "-ffreestanding",
                "-fno-builtin",
                "-funsigned-char",
                "-fno-exceptions",
                "-fno-rtti",
                "-fno-threadsafe-statics",
                "-fno-use-cxa-atexit",
                "-fno-c++-static-destructors",
                "-fno-unwind-tables",
                "-fno-asynchronous-unwind-tables",
                "-Xclang",
                "-mno-constructor-aliases",
                "-Xclang",
                "-disable-O0-optnone",
                "-nostdinc",
            ]
            .map(String::from),
        );
        args.extend([
            format!("-I{}", s(headers)),
            format!("-isystem{}", s(resource.join("include"))),
        ]);
        args.extend(
            [
                "-Werror",
                "-Wno-error=cpp",
                "-Wno-error=ignored-qualifiers",
                "-Wno-error=non-c-typedef-for-linkage",
                "-Wno-error=implicit-const-int-float-conversion",
            ]
            .map(String::from),
        );
        args.extend(self.clang_args.clone());
        Ok(args)
    }
    pub fn check_target(&self, ir: &str) -> Result<()> {
        for (k, v) in [("triple", &self.triple), ("datalayout", &self.layout)] {
            ensure!(
                ir.lines()
                    .filter(|l| l.starts_with(&format!("target {k} = ")))
                    .collect::<Vec<_>>()
                    == vec![format!("target {k} = \"{v}\"")],
                "IR target {k} mismatch"
            );
        }
        Ok(())
    }
    pub fn compile(&self) -> Result<()> {
        self.verify()?;
        if let Some(p) = &self.output {
            fs::create_dir_all(p.parent().unwrap())?;
        }
        if self.source.extension().is_some_and(|e| e == "c") && self.mode.starts_with("preprocess-")
        {
            return self.preprocess_c();
        }
        let mut args = self.clang_base()?;
        match self.mode.as_str() {
            "preprocess-deps" => {
                args.extend(["-M".into(), "-MG".into(), "-MP".into(), s(&self.source)]);
                self.call("clang", &args, false)?;
            }
            "preprocess-macros" => {
                if let Some(dep) = &self.dependency {
                    args.extend([
                        "-M".into(),
                        "-MP".into(),
                        "-MF".into(),
                        s(dep),
                        s(&self.source),
                    ]);
                    self.call("clang", &args, false)?;
                    nonempty(dep)?;
                } else if let Some(out) = &self.output {
                    args.extend([
                        "-E".into(),
                        "-CC".into(),
                        s(&self.source),
                        "-o".into(),
                        s(out),
                    ]);
                    self.call("clang", &args, false)?;
                } else {
                    args.extend(["-dM".into(), "-E".into(), s(&self.source)]);
                    self.call("clang", &args, false)?;
                }
            }
            "compile-cpp" => {
                let out = self.output.as_ref().context("missing object")?;
                let bc = suffix(out, ".stcxx.bc");
                let ir = suffix(out, ".stcxx.ll");
                let cbe = suffix(out, ".stcxx.module.cbe");
                remove(out)?;
                remove(suffix(out, ".stcxx.json"))?;
                args.extend([
                    "-emit-llvm".into(),
                    "-c".into(),
                    s(&self.source),
                    "-o".into(),
                    s(&bc),
                ]);
                let dep = self
                    .dependency
                    .clone()
                    .unwrap_or_else(|| out.with_extension("d"));
                args.extend(["-MMD".into(), "-MF".into(), s(dep), "-MT".into(), s(out)]);
                write(
                    suffix(out, ".stcxx-command.txt"),
                    args.iter().map(|a| quote(a)).collect::<Vec<_>>().join(" ") + "\n",
                )?;
                self.call("clang", &args, false)?;
                self.call("llvm-dis", &[s(&bc), "-o".into(), s(&ir)], false)?;
                self.check_target(&text(&ir)?)?;
                self.call("llvm-cbe", &[s(&bc), "-o".into(), s(&cbe)], false)?;
                let placeholder = suffix(out, ".stcxx-placeholder.c");
                let rel = out.with_extension("rel");
                write(
                    &placeholder,
                    format!(
                        "void __stcxx_placeholder_{}(void) {{}}\n",
                        &digest(s(&self.source) + "\n" + &s(out))[..16]
                    ),
                )?;
                let result = run(
                    &self.sdcc,
                    &[
                        "-mmcs251".into(),
                        "--model-large".into(),
                        "--stack-auto".into(),
                        "--std-sdcc11".into(),
                        "--opt-code-size".into(),
                        "--less-pedantic".into(),
                        "-c".into(),
                        s(&placeholder),
                        "-o".into(),
                        s(&rel),
                    ],
                    out.parent(),
                    false,
                    None,
                );
                remove(placeholder)?;
                result?;
                fs::copy(&rel, out)?;
                write_json(
                    suffix(out, ".stcxx.json"),
                    &json!({"schema_version":1,"source":s(&self.source),"source_sha256":hash(&self.source)?,"object":s(out),"object_sha256":hash(out)?,"bitcode":s(&bc),"bitcode_sha256":hash(&bc)?,"ir_sha256":hash(&ir)?,"cbe_sha256":hash(&cbe)?,"target_triple":self.triple,"data_layout":self.layout,"optimization":self.optimization}),
                )?;
            }
            "compile-c" => {
                let out = self.output.as_ref().context("missing C object")?;
                let rel = out.with_extension("rel");
                remove(out)?;
                remove(&rel)?;
                let mut flags = self.sdcc_args.clone();
                if !flags.contains(&"--stack-auto".into()) {
                    flags.push("--stack-auto".into());
                }
                flags.extend([s(&self.source), "-o".into(), s(&rel)]);
                run(&self.sdcc, &flags, rel.parent(), false, None)?;
                fs::copy(&rel, out)?;
                write_json(
                    suffix(&rel, ".stcxx-c.json"),
                    &json!({"schema_version":1,"source":s(&self.source),"source_sha256":hash(&self.source)?,"original_rel":s(&rel),"original_rel_sha256":hash(&rel)?,"sdcc":s(&self.sdcc),"sdcc_flags":self.sdcc_args,"clang":s(self.tool("clang")),"clang_flags":self.clang_args,"target_triple":self.triple}),
                )?;
            }
            _ => bail!("invalid compile mode"),
        }
        Ok(())
    }
    fn preprocess_c(&self) -> Result<()> {
        let mut args = self.arguments.clone();
        if let Some(i) = args.iter().position(|a| a == "-MF") {
            args.truncate(i);
        }
        args.extend(["-x".into(), "c".into(), s(&self.source)]);
        let tmp = tempfile::tempdir()?;
        run(&self.sdcc, &args, Some(tmp.path()), false, None)?;
        if let Some(dep) = &self.dependency {
            let generated = tmp
                .path()
                .join(self.source.file_name().unwrap())
                .with_extension("d");
            nonempty(&generated)?;
            atomic_write(dep, &fs::read(generated)?)?;
        }
        Ok(())
    }
    pub fn link(&self) -> Result<()> {
        crate::link::pipeline(self)
    }
}
pub fn size(path: &Path) -> Result<()> {
    let report = text(path)?;
    let re = regex::Regex::new(
        r"(?m)^\s*(ROM/EPROM/FLASH|PAGED EXT\. RAM|EXTERNAL RAM)\s+\S+\s+\S+\s+(\d+)",
    )?;
    let mut program = None;
    let mut ram = 0u64;
    for row in re.captures_iter(&report) {
        let n = row[2].parse::<u64>()?;
        if &row[1] == "ROM/EPROM/FLASH" {
            program = Some(n);
        } else {
            ram += n;
        }
    }
    let stack = regex::Regex::new(r"Stack starts at: 0x([0-9A-Fa-f]+)")?;
    if let Some(m) = stack.captures(&report) {
        ram += u64::from_str_radix(&m[1], 16)?;
    } else {
        for line in report.lines().filter(|l| l.starts_with("0x")) {
            ram += line
                .split('|')
                .skip(1)
                .filter(|s| !s.trim().is_empty())
                .count() as u64;
        }
    }
    println!(
        "STC_PROGRAM_BYTES {}\nSTC_RAM_BYTES {ram}",
        program.context("unrecognized memory report")?
    );
    Ok(())
}
