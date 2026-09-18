use crate::util::*;
use anyhow::{Context, Result, ensure};
use serde_json::json;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    io::{Cursor, Read, Write},
    path::{Path, PathBuf},
};
use zip::{CompressionMethod, ZipArchive, ZipWriter, write::SimpleFileOptions};

fn unpack(archive: &Path) -> Result<BTreeMap<String, Vec<u8>>> {
    let mut packed = ZipArchive::new(fs::File::open(archive)?)?;
    let mut files = BTreeMap::new();
    for i in 0..packed.len() {
        let mut f = packed.by_index(i)?;
        safe_relative(f.name())?;
        ensure!(f.is_file(), "non-file core entry");
        let name = f.name().to_owned();
        let mut bytes = Vec::new();
        f.read_to_end(&mut bytes)?;
        ensure!(
            files.insert(name.clone(), bytes).is_none(),
            "duplicate core entry: {name}"
        );
    }
    let manifest: serde_json::Value = serde_json::from_slice(
        &files
            .remove("manifest.json")
            .context("missing core manifest")?,
    )?;
    ensure!(
        manifest["schema_version"] == 1,
        "unsupported core cache format"
    );
    let inventory = manifest["files"]
        .as_object()
        .context("missing core inventory")?;
    ensure!(
        files.contains_key("core.lib")
            && files.keys().collect::<BTreeSet<_>>() == inventory.keys().collect(),
        "incomplete core cache"
    );
    for (name, bytes) in &files {
        ensure!(
            digest(bytes) == string(&inventory[name])?,
            "core cache SHA-256 mismatch: {name}"
        );
    }
    Ok(files)
}
pub fn archive(sdar: &Path, archive: &Path, object: &Path, flags: &[String]) -> Result<()> {
    let sdar = if sdar.is_file() {
        sdar.to_path_buf()
    } else {
        suffix(sdar, std::env::consts::EXE_SUFFIX)
    };
    let rel = if object.extension().is_some_and(|e| e == "o") {
        object.with_extension("rel")
    } else {
        object.to_path_buf()
    };
    nonempty(&rel)?;
    let library = archive.with_extension("lib");
    if archive.file_name().is_none_or(|n| n != "core.a") {
        ensure!(
            rel.file_name().is_none_or(|n| n != "stcxx_heap.c.rel"),
            "heap cannot enter a non-core archive"
        );
        let mut argv = flags.to_vec();
        argv.extend([s(archive), s(rel)]);
        run(&sdar, &argv, None, false, None)?;
        fs::copy(archive, library)?;
        return Ok(());
    }
    let base = archive.parent().context("missing archive directory")?;
    let mut files = if archive.exists() {
        let p = unpack(archive)?;
        write(&library, &p["core.lib"])?;
        p
    } else {
        remove(&library)?;
        BTreeMap::new()
    };
    if rel.file_name().is_none_or(|n| n != "stcxx_heap.c.rel") {
        let mut argv = flags.to_vec();
        argv.extend([s(&library), s(&rel)]);
        run(&sdar, &argv, None, false, None)?;
    }
    files.insert(
        "core.lib".into(),
        if library.exists() {
            fs::read(&library)?
        } else {
            b"!<arch>\n".to_vec()
        },
    );
    let obj = rel.with_extension("o");
    let mut paths = vec![rel.clone(), obj.clone()];
    if rel.with_extension("lst").is_file() {
        paths.push(rel.with_extension("lst"));
    }
    for ext in [".stcxx.json", ".stcxx.bc", ".stcxx.ll", ".stcxx.module.cbe"] {
        let p = suffix(&obj, ext);
        if p.exists() {
            paths.push(p);
        }
    }
    let metadata = suffix(&rel, ".stcxx-c.json");
    if metadata.exists() {
        paths.push(metadata);
    }
    for p in paths {
        let name = p
            .strip_prefix(base)
            .context("object outside core directory")?
            .to_string_lossy()
            .replace('\\', "/");
        safe_relative(&name)?;
        files.insert(name, fs::read(p)?);
    }
    let inventory: BTreeMap<_, _> = files.iter().map(|(n, b)| (n.clone(), digest(b))).collect();
    files.insert(
        "manifest.json".into(),
        serde_json::to_vec_pretty(&json!({"schema_version":1,"files":inventory}))?,
    );
    let mut packed = ZipWriter::new(Cursor::new(Vec::new()));
    for (name, bytes) in files {
        packed.start_file(
            name,
            SimpleFileOptions::default().compression_method(CompressionMethod::Deflated),
        )?;
        packed.write_all(&bytes)?;
    }
    atomic_write(archive, &packed.finish()?.into_inner())
}
pub fn materialize(archive: &Path, work: &Path) -> Result<PathBuf> {
    if archive.file_name().is_none_or(|n| n != "core.a") || !fs::read(archive)?.starts_with(b"PK") {
        nonempty(archive.with_extension("lib"))?;
        return Ok(archive.to_path_buf());
    }
    let files = unpack(archive)?;
    let destination = work.join("core-cache").join(hash(archive)?);
    for (name, bytes) in &files {
        let path = destination.join(safe_relative(name)?);
        let mut bytes = bytes.clone();
        if name.ends_with(".o.stcxx.json") {
            let mut meta: serde_json::Value = serde_json::from_slice(&bytes)?;
            let obj = destination.join(name.trim_end_matches(".stcxx.json"));
            meta["object"] = json!(s(&obj));
            meta["bitcode"] = json!(s(suffix(obj, ".stcxx.bc")));
            bytes = serde_json::to_vec_pretty(&meta)?;
        }
        if name.ends_with(".rel.stcxx-c.json") {
            let mut meta: serde_json::Value = serde_json::from_slice(&bytes)?;
            meta["original_rel"] =
                json!(s(destination.join(name.trim_end_matches(".stcxx-c.json"))));
            bytes = serde_json::to_vec_pretty(&meta)?;
        }
        write(path, bytes)?;
    }
    let native = destination.join("core.a");
    write(&native, &files["core.lib"])?;
    Ok(native)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cache_rejects_tampered_payload_and_missing_members() {
        let temp = tempfile::tempdir().unwrap();
        for (name, payload, inventory) in [
            (
                "valid",
                b"original".as_slice(),
                json!({"core.lib":digest("original")}),
            ),
            (
                "tampered",
                b"changed".as_slice(),
                json!({"core.lib":digest("original")}),
            ),
            (
                "missing",
                b"original".as_slice(),
                json!({"core.lib":digest("original"),"missing.o":digest("x")}),
            ),
        ] {
            let path = temp.path().join(name);
            let mut zip = ZipWriter::new(fs::File::create(&path).unwrap());
            zip.start_file("core.lib", SimpleFileOptions::default())
                .unwrap();
            zip.write_all(payload).unwrap();
            zip.start_file("manifest.json", SimpleFileOptions::default())
                .unwrap();
            zip.write_all(
                &serde_json::to_vec(&json!({"schema_version":1,"files":inventory})).unwrap(),
            )
            .unwrap();
            zip.finish().unwrap();
            assert_eq!(unpack(&path).is_ok(), name == "valid");
        }
    }
}
