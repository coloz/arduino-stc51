use anyhow::{Context, Result, bail, ensure};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::{Read, Write},
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

pub fn text(path: impl AsRef<Path>) -> Result<String> {
    let p = path.as_ref();
    Ok(fs::read_to_string(p)
        .with_context(|| format!("read {}", p.display()))?
        .replace("\r\n", "\n"))
}
pub fn write(path: impl AsRef<Path>, data: impl AsRef<[u8]>) -> Result<()> {
    let p = path.as_ref();
    if let Some(parent) = p.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(p, data).with_context(|| format!("write {}", p.display()))
}
pub fn json(path: impl AsRef<Path>) -> Result<Value> {
    Ok(serde_json::from_str(&text(path)?)?)
}
pub fn write_json(path: impl AsRef<Path>, value: &Value) -> Result<()> {
    write(path, serde_json::to_string_pretty(value)? + "\n")
}
pub fn digest(bytes: impl AsRef<[u8]>) -> String {
    format!("{:x}", Sha256::digest(bytes.as_ref()))
}
pub fn hash(path: impl AsRef<Path>) -> Result<String> {
    let mut f = fs::File::open(path.as_ref())
        .with_context(|| format!("hash {}", path.as_ref().display()))?;
    let mut hasher = Sha256::new();
    let mut b = [0; 65536];
    loop {
        let n = f.read(&mut b)?;
        if n == 0 {
            break;
        }
        hasher.update(&b[..n]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}
pub fn check_hash(path: impl AsRef<Path>, expected: &str) -> Result<()> {
    ensure!(
        hash(&path)? == expected,
        "SHA-256 mismatch: {}",
        path.as_ref().display()
    );
    Ok(())
}
pub fn nonempty(path: impl AsRef<Path>) -> Result<()> {
    ensure!(
        fs::metadata(path.as_ref())
            .map(|m| m.is_file() && m.len() > 0)
            .unwrap_or(false),
        "missing or empty output: {}",
        path.as_ref().display()
    );
    Ok(())
}
pub fn absolute(path: impl AsRef<Path>) -> Result<PathBuf> {
    Ok(std::path::absolute(path)?)
}
pub fn s(path: impl AsRef<Path>) -> String {
    path.as_ref().to_string_lossy().into_owned()
}
pub fn suffix(path: impl AsRef<Path>, ext: &str) -> PathBuf {
    PathBuf::from(s(path) + ext)
}
pub fn remove(path: impl AsRef<Path>) -> Result<()> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(e.into()),
    }
}
pub fn exe(dir: &Path, name: &str) -> PathBuf {
    dir.join(format!("{name}{}", std::env::consts::EXE_SUFFIX))
}
pub fn string(value: &Value) -> Result<&str> {
    value.as_str().context("expected JSON string")
}

#[derive(Debug)]
pub struct ProcessError(pub i32);
impl std::fmt::Display for ProcessError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "compiler exited with status {}", self.0)
    }
}
impl std::error::Error for ProcessError {}

// Display only: execution always uses argv directly, never a shell.
pub fn quote(arg: &str) -> String {
    if !arg.is_empty() && !arg.chars().any(|c| c.is_whitespace() || c == '"') {
        return arg.into();
    }
    let mut out = String::from("\"");
    let mut slashes = 0;
    for c in arg.chars() {
        if c == '\\' {
            slashes += 1;
            continue;
        }
        out.extend(std::iter::repeat_n(
            '\\',
            if c == '"' { slashes * 2 + 1 } else { slashes },
        ));
        slashes = 0;
        out.push(c);
    }
    out.extend(std::iter::repeat_n('\\', slashes * 2));
    out.push('"');
    out
}
pub fn run(
    program: &Path,
    args: &[String],
    cwd: Option<&Path>,
    capture: bool,
    log: Option<&Path>,
) -> Result<Vec<u8>> {
    // Keep dependency and preprocessor stdout machine-readable. Commands use stderr.
    eprintln!(
        "{} {}",
        quote(&s(program)),
        args.iter().map(|a| quote(a)).collect::<Vec<_>>().join(" ")
    );
    let mut cmd = Command::new(program);
    cmd.args(args).stdin(Stdio::null());
    if let Some(p) = cwd {
        cmd.current_dir(p);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000);
    }
    if let Some(log) = log {
        let mut child = cmd
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .with_context(|| format!("start {}", program.display()))?;
        let stdout = child.stdout.take().unwrap();
        let stderr = child.stderr.take().unwrap();
        let out = std::thread::spawn(move || -> std::io::Result<Vec<u8>> {
            let mut reader = stdout;
            let mut bytes = Vec::new();
            let mut buf = [0; 8192];
            loop {
                let n = reader.read(&mut buf)?;
                if n == 0 {
                    break;
                }
                if !capture {
                    std::io::stdout().write_all(&buf[..n])?;
                }
                bytes.extend_from_slice(&buf[..n]);
            }
            Ok(bytes)
        });
        let err = std::thread::spawn(move || -> std::io::Result<Vec<u8>> {
            let mut reader = stderr;
            let mut bytes = Vec::new();
            let mut buf = [0; 8192];
            loop {
                let n = reader.read(&mut buf)?;
                if n == 0 {
                    break;
                }
                std::io::stderr().write_all(&buf[..n])?;
                bytes.extend_from_slice(&buf[..n]);
            }
            Ok(bytes)
        });
        let status = child.wait()?;
        let output = out
            .join()
            .map_err(|_| anyhow::anyhow!("stdout relay failed"))??;
        let errors = err
            .join()
            .map_err(|_| anyhow::anyhow!("stderr relay failed"))??;
        let mut combined = output.clone();
        combined.extend(errors);
        write(log, combined)?;
        if !status.success() {
            return Err(ProcessError(status.code().unwrap_or(1)).into());
        }
        Ok(output)
    } else if capture {
        let output = cmd
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .output()?;
        if !output.status.success() {
            std::io::stderr().write_all(&output.stdout)?;
            return Err(ProcessError(output.status.code().unwrap_or(1)).into());
        }
        Ok(output.stdout)
    } else {
        let status = cmd
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .status()?;
        if !status.success() {
            return Err(ProcessError(status.code().unwrap_or(1)).into());
        }
        Ok(Vec::new())
    }
}
pub fn safe_relative(name: &str) -> Result<&Path> {
    let path = Path::new(name);
    ensure!(
        !name.is_empty()
            && !name.contains(['\\', ':'])
            && !path.is_absolute()
            && name
                .split('/')
                .all(|c| !c.is_empty() && c != "." && c != ".."),
        "unsafe archive entry: {name}"
    );
    Ok(path)
}
// Optional analyses must retain diagnostics as evidence without reporting a
// failed probe as a build error when the original SDCC object remains valid.
pub fn probe(program: &Path, args: &[String]) -> Result<std::process::Output> {
    eprintln!(
        "{} {}",
        quote(&s(program)),
        args.iter().map(|a| quote(a)).collect::<Vec<_>>().join(" ")
    );
    let mut command = Command::new(program);
    command.args(args).stdin(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    Ok(command.output()?)
}
pub fn atomic_write(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut pending = tempfile::NamedTempFile::new_in(path.parent().context("missing parent")?)?;
    pending.write_all(bytes)?;
    pending.persist(path).map_err(|e| e.error)?;
    Ok(())
}
pub fn command_flag(args: &[String], flag: &str) -> Result<String> {
    let values: Vec<_> = args
        .windows(2)
        .filter(|p| p[0] == flag)
        .map(|p| p[1].clone())
        .collect();
    if values.len() != 1 {
        bail!("expected one {flag} argument");
    }
    Ok(values[0].clone())
}

#[cfg(test)]
mod tests {
    use super::*;
    const ARGUMENTS: [&str; 4] = [
        "中文 path",
        "literal & $() ;",
        "quote\"end",
        "C:\\trailing space\\",
    ];
    #[test]
    #[ignore = "subprocess fixture"]
    fn process_fixture() {
        let arguments: Vec<_> = std::env::args().skip(5).collect();
        assert_eq!(arguments, ARGUMENTS);
        println!("native-stdout 中文");
        eprintln!("native-stderr 中文");
        std::process::exit(7);
    }
    #[test]
    fn subprocess_preserves_arguments_streams_and_failure() {
        let work = tempfile::tempdir().unwrap();
        let log = work.path().join("compiler.log");
        let args: Vec<_> = [
            "--exact",
            "--ignored",
            "--nocapture",
            "util::tests::process_fixture",
        ]
        .into_iter()
        .chain(ARGUMENTS)
        .map(String::from)
        .collect();
        let error = run(
            &std::env::current_exe().unwrap(),
            &args,
            None,
            true,
            Some(&log),
        )
        .unwrap_err();
        assert_eq!(error.downcast_ref::<ProcessError>().unwrap().0, 7);
        let output = text(log).unwrap();
        assert!(output.contains("native-stdout 中文") && output.contains("native-stderr 中文"));
    }
    #[test]
    fn argument_display() {
        assert_eq!(quote("-DF_CPU=12000000L"), "-DF_CPU=12000000L");
        assert_eq!(
            quote("C:\\path with spaces\\"),
            "\"C:\\path with spaces\\\\\""
        );
        assert_eq!(quote(""), "\"\"");
    }
    #[test]
    fn reject_archive_traversal() {
        for p in [
            "../outside",
            "/absolute",
            "C:/bad",
            "a\\b",
            "a/../b",
            "a//b",
        ] {
            assert!(safe_relative(p).is_err());
        }
    }
}
