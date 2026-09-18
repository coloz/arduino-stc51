//! Recompile the reachable native C source closure. Clang supplies source ranges;
//! SDCC still owns code generation and storage. No REL relocations are rewritten.
use crate::{
    driver::Driver,
    link::{archive_members, rel_symbols},
    util::*,
};
use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
};

#[derive(Clone)]
struct Decl {
    name: String,
    body: Option<(usize, usize)>,
    range: (usize, usize),
    refs: BTreeSet<String>,
    external: bool,
    removable_data: bool,
}
struct Unit {
    original: PathBuf,
    source: PathBuf,
    bytes: Vec<u8>,
    meta: Value,
    decls: Vec<Decl>,
    selected: BTreeSet<String>,
}
fn refs(node: &Value, out: &mut BTreeSet<String>) {
    if let Some(name) = node["referencedDecl"]["name"].as_str() {
        out.insert(name.into());
    }
    if let Some(children) = node["inner"].as_array() {
        for child in children {
            refs(child, out);
        }
    }
}
fn has_assembly(node: &Value) -> bool {
    matches!(
        node["kind"].as_str(),
        Some("GCCAsmStmt" | "MSAsmStmt" | "FileScopeAsmDecl")
    ) || node["inner"]
        .as_array()
        .is_some_and(|a| a.iter().any(has_assembly))
}
fn location(node: &Value, source: &Path, size: usize) -> Result<Option<(usize, usize)>> {
    if node.get("spellingLoc").is_some() || node.get("expansionLoc").is_some() {
        return Ok(None);
    }
    if node.get("includedFrom").is_some() {
        return Ok(None);
    }
    if let Some(file) = node["file"].as_str()
        && absolute(file)? != source
    {
        return Ok(None);
    }
    let Some(start) = node["offset"].as_u64() else {
        return Ok(None);
    };
    let len = node["tokLen"].as_u64().unwrap_or(0);
    ensure!(
        start + len <= size as u64,
        "Clang source range exceeds source"
    );
    Ok(Some((start as usize, len as usize)))
}
fn range(node: &Value, source: &Path, size: usize) -> Result<Option<(usize, usize)>> {
    let Some((begin, _)) = location(&node["range"]["begin"], source, size)? else {
        return Ok(None);
    };
    let Some((end, len)) = location(&node["range"]["end"], source, size)? else {
        return Ok(None);
    };
    ensure!(begin <= end + len, "reversed Clang source range");
    Ok(Some((begin, end + len)))
}
fn inspect(ast: &Value, source: &Path, bytes: &[u8]) -> Result<Vec<Decl>> {
    ensure!(
        ast["kind"] == "TranslationUnitDecl",
        "not a Clang translation unit"
    );
    let mut declarations = Vec::new();
    for node in ast["inner"]
        .as_array()
        .context("missing Clang declarations")?
    {
        if node["isImplicit"] == true {
            continue;
        }
        let kind = node["kind"].as_str().unwrap_or("");
        if !["FunctionDecl", "VarDecl", "FileScopeAsmDecl"].contains(&kind) {
            continue;
        }
        let children = node["inner"].as_array();
        let body = children.and_then(|a| a.iter().find(|n| n["kind"] == "CompoundStmt"));
        if kind == "FunctionDecl" && body.is_none() {
            continue;
        }
        let Some(decl_range) = range(node, source, bytes.len())? else {
            if kind == "VarDecl" {
                let mut r = BTreeSet::new();
                refs(node, &mut r);
                if !r.is_empty() {
                    declarations.push(Decl {
                        name: String::new(),
                        body: None,
                        range: (0, 0),
                        refs: r,
                        external: false,
                        removable_data: false,
                    });
                }
            }
            continue;
        };
        ensure!(
            !has_assembly(node),
            "assembly prevents safe C source trimming"
        );
        let name = node["name"]
            .as_str()
            .context("unnamed C declaration")?
            .to_owned();
        let mut references = BTreeSet::new();
        refs(node, &mut references);
        let body_range = if let Some(body) = body {
            let (start, end) = range(body, source, bytes.len())?
                .context("macro-generated function body is not splittable")?;
            ensure!(
                decl_range.0 <= start
                    && end <= decl_range.1
                    && bytes.get(start) == Some(&b'{')
                    && bytes.get(end - 1) == Some(&b'}'),
                "invalid C function body range"
            );
            Some((start, end))
        } else {
            None
        };
        let ty = node["type"]["qualType"].as_str().unwrap_or("");
        // Discard only immutable byte arrays. All state and callback initializers
        // remain shared in the original translation unit.
        let mut declaration_end = decl_range.1;
        while bytes
            .get(declaration_end)
            .is_some_and(u8::is_ascii_whitespace)
        {
            declaration_end += 1;
        }
        let removable_data = kind == "VarDecl"
            && bytes.get(declaration_end) == Some(&b';')
            && node["storageClass"] != "extern"
            && node.get("init").is_some()
            && (ty.starts_with("const unsigned char[")
                || ty.starts_with("const uint8_t[")
                || ty.starts_with("const char["))
            && references.is_empty();
        declarations.push(Decl {
            name,
            body: body_range,
            range: if removable_data {
                (decl_range.0, declaration_end + 1)
            } else {
                decl_range
            },
            refs: references,
            external: node["storageClass"] != "static",
            removable_data,
        });
    }
    // Clang gives comma-separated variables overlapping declaration ranges.
    // Retain those declarations intact rather than deleting another variable.
    let overlaps: Vec<_> = declarations
        .iter()
        .map(|d| {
            declarations.iter().any(|other| {
                !std::ptr::eq(d, other) && d.range.0 < other.range.1 && other.range.0 < d.range.1
            })
        })
        .collect();
    for (decl, overlap) in declarations.iter_mut().zip(overlaps) {
        if overlap {
            decl.removable_data = false;
        }
    }
    ensure!(!declarations.is_empty(), "no source-owned C declarations");
    let mut ranges: Vec<_> = declarations.iter().filter_map(|d| d.body).collect();
    ranges.sort();
    ensure!(
        ranges.windows(2).all(|p| p[0].1 <= p[1].0),
        "overlapping C functions"
    );
    Ok(declarations)
}
fn oversized(bytes: &[u8], code_limit: u64, xram_limit: u64) -> Result<bool> {
    let text = std::str::from_utf8(bytes)?;
    let re = regex::Regex::new(r"(?m)^A (\S+) size ([0-9A-Fa-f]+) flags ")?;
    let mut code = 0;
    let mut xram = 0;
    for m in re.captures_iter(text) {
        let size = u64::from_str_radix(&m[2], 16)?;
        if m[1].starts_with("CSEG") || m[1].starts_with("CONST") {
            code += size;
        }
        if ["XSEG", "XISEG"].contains(&&m[1]) {
            xram += size;
        }
    }
    Ok(code > code_limit || xram > xram_limit)
}
fn strings(value: &Value) -> Result<Vec<String>> {
    value
        .as_array()
        .context("missing C argument vector")?
        .iter()
        .map(|v| Ok(string(v)?.into()))
        .collect()
}
pub fn trim(d: &Driver, arguments: &[String], work: &Path) -> Result<Vec<String>> {
    let code_limit = command_flag(arguments, "--code-size")?.parse::<u64>()?;
    let xram_limit = command_flag(arguments, "--xram-size")?.parse::<u64>()?;
    let mut units = Vec::new();
    let mut native = Vec::new();
    let resource = String::from_utf8(d.call("clang", &["--print-resource-dir".into()], true)?)?;
    let mut classifications = Vec::new();
    for arg in arguments {
        if arg.ends_with(".lib") {
            for (_, bytes) in archive_members(Path::new(arg))? {
                native.push(bytes);
            }
            continue;
        }
        if !arg.ends_with(".rel") {
            continue;
        }
        let path = PathBuf::from(arg);
        let bytes = fs::read(&path)?;
        let metadata = suffix(&path, ".stcxx-c.json");
        if !arg.replace('\\', "/").contains("/libraries/") || !metadata.is_file() {
            native.push(bytes);
            continue;
        }
        let meta = json(&metadata)?;
        let source = PathBuf::from(string(&meta["source"])?);
        check_hash(&source, string(&meta["source_sha256"])?)?;
        check_hash(&path, string(&meta["original_rel_sha256"])?)?;
        let source_bytes = fs::read(&source)?;
        let mut args = vec![
            "-x".into(),
            "c".into(),
            "-fsyntax-only".into(),
            "-fno-color-diagnostics".into(),
            "-Xclang".into(),
            "-ast-dump=json".into(),
            format!("--target={}", d.triple),
            "-std=gnu11".into(),
            "-ffreestanding".into(),
            "-funsigned-char".into(),
            "-nostdinc".into(),
            format!("-I{}", s(d.platform.join("cores/STC/cpp"))),
            format!("-isystem{}", s(Path::new(resource.trim()).join("include"))),
            "-D__code=".into(),
            "-D__reentrant=".into(),
            // Select the same hardware branches as the backend. Unsupported
            // SFR/assembly constructs make the optional probe retain the TU.
            "-D__SDCC=1".into(),
            "-D__SDCC_mcs251=1".into(),
        ];
        let flags = meta.get("clang_flags").unwrap_or(&meta["clang_arguments"]);
        args.extend(strings(flags)?);
        args.push(s(&source));
        let analysis = (|| -> Result<Vec<Decl>> {
            let output = probe(&d.tool("clang"), &args)?;
            ensure!(
                output.status.success(),
                "Clang source analysis unavailable: {}",
                String::from_utf8_lossy(&output.stderr)
            );
            inspect(
                &serde_json::from_slice(&output.stdout)?,
                &source,
                &source_bytes,
            )
        })();
        match analysis {
            Ok(decls) => {
                classifications.push(json!({"source":s(&source),"mode":"source-closure"}));
                units.push(Unit {
                    original: path,
                    source,
                    bytes: source_bytes,
                    meta,
                    decls,
                    selected: BTreeSet::new(),
                });
            }
            Err(error) => {
                ensure!(
                    !oversized(&bytes, code_limit, xram_limit)?,
                    "oversized C object cannot be safely trimmed: {}: {error:#}",
                    source.display()
                );
                classifications.push(
                    json!({"source":s(source),"mode":"original","reason":format!("{error:#}")}),
                );
                native.push(bytes);
            }
        }
    }
    if units.is_empty() {
        return Ok(arguments.to_vec());
    }
    let mut needed = BTreeSet::new();
    for bytes in &native {
        let (_, refs) = rel_symbols(bytes)?;
        needed.extend(
            refs.into_iter()
                .map(|n| n.strip_prefix('_').unwrap_or(&n).to_owned()),
        );
    }
    for unit in &units {
        for decl in &unit.decls {
            if decl.body.is_none() && !decl.removable_data {
                needed.extend(decl.refs.clone());
            }
        }
    }
    loop {
        let mut changed = false;
        for unit in &mut units {
            let mut pending: Vec<_> = unit
                .decls
                .iter()
                .filter(|decl| {
                    decl.external && needed.contains(&decl.name)
                        || decl.body.is_none() && !decl.removable_data
                })
                .map(|d| d.name.clone())
                .collect();
            // Private functions referenced by retained file-scope initializers.
            for decl in &unit.decls {
                if decl.body.is_none() && !decl.removable_data {
                    pending.extend(decl.refs.clone());
                }
            }
            while let Some(name) = pending.pop() {
                if unit.selected.contains(&name) {
                    continue;
                }
                if let Some(decl) = unit.decls.iter().find(|d| d.name == name) {
                    unit.selected.insert(name);
                    changed = true;
                    pending.extend(decl.refs.clone());
                    for r in &decl.refs {
                        if !unit.decls.iter().any(|d| &d.name == r && !d.external)
                            && needed.insert(r.clone())
                        {
                            changed = true;
                        }
                    }
                }
            }
        }
        if !changed {
            break;
        }
    }
    let mut replacements = BTreeMap::new();
    let mut audits = Vec::new();
    for unit in units {
        let mut edits = Vec::new();
        let mut removed = BTreeSet::new();
        let mut expected = BTreeSet::new();
        for decl in &unit.decls {
            if let Some(range) = decl.body {
                if !unit.selected.contains(&decl.name) {
                    edits.push((range, ";"));
                    removed.insert(format!("_{}", decl.name));
                } else if decl.external {
                    expected.insert(format!("_{}", decl.name));
                }
            } else if decl.removable_data && !unit.selected.contains(&decl.name) {
                edits.push((decl.range, ""));
                removed.insert(format!("_{}", decl.name));
            }
        }
        if edits.is_empty() {
            continue;
        }
        edits.sort_by_key(|(r, _)| r.0);
        ensure!(
            edits.windows(2).all(|p| p[0].0.1 <= p[1].0.0),
            "overlapping source edits"
        );
        let mut generated = unit.bytes.clone();
        for ((start, end), replacement) in edits.into_iter().rev() {
            generated.splice(start..end, replacement.bytes());
        }
        let directory = work
            .join("native-source-closure")
            .join(&digest(s(&unit.original))[..16]);
        fs::create_dir_all(&directory)?;
        let source = directory.join(unit.source.file_name().unwrap());
        let rel = directory.join(unit.original.file_name().unwrap());
        write(&source, &generated)?;
        let flags = unit
            .meta
            .get("sdcc_flags")
            .unwrap_or(&unit.meta["sdcc_arguments"]);
        let mut args = strings(flags)?;
        args.extend([
            format!("-I{}", s(unit.source.parent().unwrap())),
            s(&source),
            "-o".into(),
            s(&rel),
        ]);
        run(
            &d.sdcc,
            &args,
            Some(&directory),
            false,
            Some(&directory.join("compile.log")),
        )?;
        let (defs, refs) = rel_symbols(&fs::read(&rel)?)?;
        ensure!(
            expected.is_subset(&defs) && defs.is_disjoint(&removed),
            "C source closure changed exported definitions"
        );
        let missing: Vec<_> = refs.intersection(&removed).collect();
        ensure!(
            missing.is_empty(),
            "C closure still references discarded symbols: {missing:?}"
        );
        audits.push(json!({"source":s(&unit.source),"source_sha256":digest(&unit.bytes),"generated":s(&source),"generated_sha256":digest(&generated),"original_rel":s(&unit.original),"output_rel":s(&rel),"output_sha256":hash(&rel)?,"retained":unit.selected,"discarded_symbols":removed}));
        replacements.insert(s(&unit.original), s(&rel));
    }
    write_json(
        work.join("native-source-closure.json"),
        &json!({"schema_version":1,"policy":"Clang-source-ranges-SDCC-single-TU-recompile","classifications":classifications,"units":audits}),
    )?;
    Ok(arguments
        .iter()
        .map(|a| replacements.get(a).unwrap_or(a).clone())
        .collect())
}
