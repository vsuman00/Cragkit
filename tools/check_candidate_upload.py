#!/usr/bin/env python3
"""Admit exact attested Python RC3 products without extracting or executing archive contents."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import tarfile
import urllib.error
import urllib.request
import zipfile
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path, PurePosixPath

REPOSITORY = "vsuman00/Cragkit"
PYTHON_VERSION = "1.0.0rc3"
PACKAGES = ("cragkit", "cragkit-langchain", "cragkit-mcp")
MAX_FILE = 32 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
EXPECTED = {}
for package in PACKAGES:
    stem = package.replace("-", "_")
    EXPECTED[f"{stem}-{PYTHON_VERSION}-py3-none-any.whl"] = (package, PYTHON_VERSION, "wheel", "pypi")
    EXPECTED[f"{stem}-{PYTHON_VERSION}.tar.gz"] = (package, PYTHON_VERSION, "sdist", "pypi")


def require(value, message):
    if not value:
        raise ValueError(message)


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def safe_name(name):
    path = PurePosixPath(name)
    require(name and "\\" not in name and not path.is_absolute() and ".." not in path.parts,
            "unsafe archive path")
    require(str(path) == name.rstrip("/"), "noncanonical archive path")


def members(path, kind):
    content = {}
    total = 0
    if kind == "wheel":
        with zipfile.ZipFile(path) as archive:
            require(len(archive.infolist()) <= 500, "too many wheel members")
            for item in archive.infolist():
                safe_name(item.filename)
                require(item.filename not in content, "duplicate wheel member")
                mode = item.external_attr >> 16
                require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), "nonregular wheel member")
                require(not item.flag_bits & 1, "encrypted wheel")
                total += item.file_size
                require(item.file_size <= MAX_FILE and total <= MAX_EXPANDED, "expanded wheel too large")
                content[item.filename] = archive.read(item) if not item.is_dir() else None
    else:
        with tarfile.open(path, "r:gz") as archive:
            count = 0
            for item in archive:
                count += 1
                require(count <= 500, "too many tar members")
                safe_name(item.name)
                require(item.name not in content, "duplicate tar member")
                require(item.isfile() or item.isdir(), "nonregular tar member")
                total += item.size
                require(item.size <= MAX_FILE and total <= MAX_EXPANDED, "expanded tar too large")
                stream = archive.extractfile(item) if item.isfile() else None
                content[item.name] = stream.read() if stream else None
    return content


def audit_archive(path, identity, readme_digest):
    package, version, kind, registry = identity
    data = members(path, kind)
    meta_names = [name for name in data if name.endswith(".dist-info/METADATA")] if kind == "wheel" else [
        name for name in data if name.count("/") == 1 and name.endswith("/PKG-INFO")]
    require(len(meta_names) == 1, "Python metadata count differs")
    metadata = BytesParser(policy=email_policy).parsebytes(data[meta_names[0]])
    require(metadata["Name"] == package and metadata["Version"] == version, "Python identity differs")
    require(metadata["Summary"] and metadata["Description-Content-Type"] == "text/markdown",
            "Python description metadata differs")
    if kind == "wheel":
        readme = metadata.get_payload(decode=True)
        require(any(name.endswith("/LICENSE") for name in data) and any(name.endswith("/NOTICE") for name in data),
                "wheel notices missing")
    else:
        root = path.name.removesuffix(".tar.gz")
        require(all(name == root or name.startswith(root + "/") for name in data), "sdist root differs")
        readme = data[root + "/README.md"]
        require(data[root + "/LICENSE"] and data[root + "/NOTICE"], "sdist notices missing")
    require(readme and len(readme) >= 100, "full README missing")
    require(hashlib.sha256(readme.rstrip(b"\n") + b"\n").hexdigest() == readme_digest,
            "README digest differs")


def registry_json(url):
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Cragkit-RC3-attestation-admission/1"})
        with urllib.request.urlopen(request, timeout=15) as response:
            require(response.status == 200, "unexpected registry status")
            value = response.read(8 * 1024 * 1024 + 1)
            require(len(value) <= 8 * 1024 * 1024, "registry response too large")
            return json.loads(value)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def require_existing_attestation(package, filename):
    provenance = registry_json(f"https://pypi.org/integrity/{package}/{PYTHON_VERSION}/{filename}/provenance")
    require(isinstance(provenance, dict) and provenance.get("version") == 1,
            "existing PyPI file lacks provenance; immutable upload cannot be repaired by skipping")
    bundles = provenance.get("attestation_bundles")
    require(isinstance(bundles, list) and bundles, "existing PyPI file lacks attestation bundles")
    for bundle in bundles:
        require(isinstance(bundle, dict), "existing provenance bundle malformed")
        publisher = bundle.get("publisher")
        require(isinstance(publisher, dict) and publisher.get("kind") == "GitHub"
                and publisher.get("repository") == REPOSITORY and publisher.get("workflow") == "publish-candidate.yml",
                "existing provenance publisher differs")
        attestations = bundle.get("attestations")
        require(isinstance(attestations, list) and attestations
                and all(isinstance(item, dict) and item.get("version") == 1 and item.get("envelope")
                        and item.get("verification_material") for item in attestations),
                "existing provenance attestations absent or malformed")
    # Presence and declared publisher checks only. Final acceptance verifies cryptographic identity and subjects.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--release-source", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require(re.fullmatch("[0-9a-f]{64}", args.manifest_sha256), "invalid manifest digest")
    manifest_path = args.input_dir / "release-manifest.json"
    require(manifest_path.is_file() and not manifest_path.is_symlink() and manifest_path.stat().st_size <= 32768,
            "manifest missing or too large")
    require(hashlib.sha256(manifest_path.read_bytes()).hexdigest() == args.manifest_sha256, "manifest digest differs")
    manifest = load_json(manifest_path)
    require(set(manifest) == {"schema_version", "repository", "source_commit", "python_version", "require_publish_attestations",
                              "security_hold", "security_review", "readme_sha256", "artifacts"}, "manifest fields differ")
    require(manifest["schema_version"] == 1 and manifest["repository"] == REPOSITORY, "manifest schema/repository differs")
    require(re.fullmatch("[0-9a-f]{40}", manifest["source_commit"]) and manifest["source_commit"] == args.release_source,
            "source identity differs")
    require(manifest["python_version"] == PYTHON_VERSION, "release version differs")
    require(manifest["require_publish_attestations"] is True, "publish attestations must be explicitly required")
    require(manifest["security_hold"] is False, "security hold absent, malformed or active")
    hold = manifest["security_review"]
    require(isinstance(hold, dict) and set(hold) == {"decision", "reviewer", "reviewed_at", "source_commit"},
            "security hold decision malformed")
    require(hold["decision"] == "approved" and isinstance(hold["reviewer"], str)
            and hold["reviewer"].strip() and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", hold["reviewed_at"])
            and hold["source_commit"] == manifest["source_commit"], "security hold absent, active or unapproved")
    readmes = manifest["readme_sha256"]
    require(set(readmes) == {f"python/{package}" for package in PACKAGES},
            "README identities differ")
    require(all(re.fullmatch("[0-9a-f]{64}", digest) for digest in readmes.values()), "invalid README digest")
    artifacts = manifest["artifacts"]
    require(isinstance(artifacts, list) and len(artifacts) == 6, "exact six Python products required")
    records = {}
    for item in artifacts:
        require(set(item) == {"filename", "sha256", "size", "kind", "package", "version", "registry"}, "artifact fields differ")
        name = item["filename"]
        require(name in EXPECTED and name not in records, "unknown or duplicate product")
        require(tuple(item[key] for key in ("package", "version", "kind", "registry")) == EXPECTED[name], "product identity differs")
        require(type(item["size"]) is int and 0 < item["size"] <= MAX_FILE and re.fullmatch("[0-9a-f]{64}", item["sha256"]),
                "invalid product size/digest")
        path = args.input_dir / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == item["size"], "product missing or size differs")
        require(hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"], "product digest differs")
        audit_archive(path, EXPECTED[name], readmes[f"python/{item['package']}"])
        records[name] = item
    require(set(records) == set(EXPECTED), "product set differs")
    require(set(p.name for p in args.input_dir.iterdir()) == set(EXPECTED) | {"release-manifest.json"}, "unexpected input files")
    missing = []
    for package in PACKAGES:
        existing = registry_json(f"https://pypi.org/pypi/{package}/{PYTHON_VERSION}/json")
        expected = {name: record for name, record in records.items() if record["package"] == package and record["registry"] == "pypi"}
        published = {item["filename"]: item for item in existing["urls"]} if existing else {}
        require(set(published) <= set(expected), "unknown existing PyPI file")
        for name, record in expected.items():
            if name in published:
                require(published[name]["digests"]["sha256"] == record["sha256"] and published[name]["size"] == record["size"],
                        "existing PyPI file conflicts")
                require_existing_attestation(package, name)
            else:
                missing.append(name)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(manifest_path, args.output_dir / manifest_path.name)
    for name in sorted(missing):
        shutil.copyfile(args.input_dir / name, args.output_dir / name)
    plan = {"schema_version": 1, "manifest_sha256": args.manifest_sha256, "missing": sorted(missing)}
    (args.output_dir / "upload-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(json.dumps(plan))


if __name__ == "__main__":
    main()
