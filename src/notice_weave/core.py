"""Explicit inventory and byte-level notice receipts. No license inference."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

MAX_CONFIG = 2 * 1024 * 1024
MAX_NOTICE = 4 * 1024 * 1024
MAX_ASSET = 256 * 1024 * 1024
MAX_FILES = 100_000
MAX_TOTAL = 1024 * 1024 * 1024


class InputError(ValueError):
    """The input cannot be interpreted safely or completely."""


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def line(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise InputError(f"{label}: expected nonempty text (at most 4096 characters)")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise InputError(f"{label}: control characters are not allowed")
    return value


def relative(value: object) -> str:
    value = line(value, "path")
    if any(x in value for x in ("\\", ":")) or any(p in ("", ".", "..") for p in value.split("/")):
        raise InputError(f"path must be a normalized relative POSIX path: {value!r}")
    return value


def fields(value: object, required: set[str], optional: set[str], label: str) -> dict:
    if not isinstance(value, dict) or required - value.keys() or value.keys() - required - optional:
        raise InputError(
            f"{label}: expected fields {sorted(required)}, optional {sorted(optional)}"
        )
    return value


def paths(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise InputError(f"{label}: expected a nonempty list")
    result = [relative(v) for v in value]
    if len(result) != len(set(result)):
        raise InputError(f"{label}: duplicate path")
    return sorted(result)


def is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def local_path(root: Path, name: str, *, directory: bool = False) -> Path:
    path = root
    parts = relative(name).split("/")
    for index, part in enumerate(parts):
        path = path / part
        info = path.lstat()
        if is_link(info):
            raise InputError(f"links and reparse points are not supported: {name!r}")
        want_dir = directory or index < len(parts) - 1
        if (want_dir and not stat.S_ISDIR(info.st_mode)) or (
            not want_dir and not stat.S_ISREG(info.st_mode)
        ):
            raise InputError(f"unexpected file type: {name!r}")
    return path


def read_limited(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise InputError(f"input exceeds {limit} bytes: {path.name!r}")
    return data


def load_manifest(path: Path) -> dict:
    data = tomllib.loads(read_limited(path, MAX_CONFIG).decode("utf-8"))
    fields(data, {"version", "inventory_roots", "components"}, set(), "manifest")
    if type(data["version"]) is not int or data["version"] != 1:
        raise InputError("manifest version must be 1")
    roots = paths(data["inventory_roots"], "inventory_roots")
    if any(b.startswith(a + "/") for a in roots for b in roots if a != b):
        raise InputError("inventory roots must not overlap")
    if not isinstance(data["components"], list) or not data["components"]:
        raise InputError("components must be a nonempty array")
    components = []
    ids: set[str] = set()
    artifacts: set[str] = set()
    notices: set[str] = set()
    for c in data["components"]:
        fields(c, {"id", "name", "version", "source", "artifacts", "notices"}, set(), "component")
        c = dict(c)
        for key in ("id", "name", "version", "source"):
            c[key] = line(c[key], key)
        if c["id"] in ids:
            raise InputError(f"duplicate component id: {c['id']!r}")
        ids.add(c["id"])
        for key in ("artifacts", "notices"):
            c[key] = paths(c[key], key)
        if artifacts.intersection(c["artifacts"]):
            raise InputError("each artifact must belong to exactly one component")
        artifacts.update(c["artifacts"])
        notices.update(c["notices"])
        components.append(c)
    if artifacts & notices:
        raise InputError("an artifact cannot also be a notice")
    if any(not any(p.startswith(r + "/") for r in roots) for p in artifacts):
        raise InputError("all artifacts must be under an inventory root")
    return {
        "version": 1,
        "inventory_roots": roots,
        "components": sorted(components, key=lambda c: c["id"]),
    }


def inventory(root: Path, roots: list[str]) -> set[str]:
    found: set[str] = set()
    pending = [local_path(root, r, directory=True) for r in roots]
    count = 0
    while pending:
        folder = pending.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                count += 1
                if count > MAX_FILES:
                    raise InputError(f"inventory exceeds {MAX_FILES} entries")
                path = Path(entry.path)
                name = path.relative_to(root).as_posix()
                relative(name)
                info = entry.stat(follow_symlinks=False)
                if is_link(info):
                    raise InputError(f"links and reparse points are not supported: {name!r}")
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode):
                    found.add(name)
                else:
                    raise InputError(f"non-regular inventory entry: {name!r}")
    return found


@dataclass
class Snapshot:
    manifest: dict
    files: dict[str, dict]
    notices: dict[str, bytes]
    uncovered: list[str]

    def lock(self) -> dict:
        if self.uncovered:
            raise InputError("cannot lock: uncovered files: " + repr(self.uncovered))
        return {
            "version": 1,
            "manifest_sha256": digest(canonical(self.manifest)),
            "files": {name: dict(info) for name, info in self.files.items()},
        }


def snapshot(manifest_path: Path) -> Snapshot:
    manifest = load_manifest(manifest_path)
    root = manifest_path.resolve().parent
    notice_paths = {p for c in manifest["components"] for p in c["notices"]}
    all_paths = notice_paths | {p for c in manifest["components"] for p in c["artifacts"]}
    if len(all_paths) > MAX_FILES:
        raise InputError("too many declared files")
    uncovered = sorted(inventory(root, manifest["inventory_roots"]) - all_paths)
    hashes = {}
    notices = {}
    total = 0
    for name in sorted(all_paths):
        path = local_path(root, name)
        limit = MAX_NOTICE if name in notice_paths else MAX_ASSET
        sha = hashlib.sha256()
        size = 0
        chunks = []
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if before.st_size > limit:
                raise InputError(f"file exceeds {limit} bytes: {name!r}")
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                total += len(chunk)
                if size > limit or total > MAX_TOTAL:
                    raise InputError("file or aggregate input byte limit exceeded")
                sha.update(chunk)
                if name in notice_paths:
                    chunks.append(chunk)
            after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise InputError(f"file changed while reading: {name!r}")
        hashes[name] = {"sha256": sha.hexdigest(), "bytes": size}
        if name in notice_paths:
            raw = b"".join(chunks)
            text = raw.decode("utf-8")
            if not text.strip() or any(ord(c) < 32 and c not in "\n\r\t" for c in text):
                raise InputError(f"notice must be nonempty UTF-8 text without controls: {name!r}")
            notices[name] = raw
    return Snapshot(manifest, hashes, notices, uncovered)


def unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_lock(path: Path) -> dict:
    data = json.loads(read_limited(path, 32 * MAX_CONFIG), object_pairs_hook=unique_object)
    fields(data, {"version", "manifest_sha256", "files"}, set(), "lock")
    if (
        type(data["version"]) is not int
        or data["version"] != 1
        or not isinstance(data["files"], dict)
    ):
        raise InputError("unsupported lock structure")
    for value in [data["manifest_sha256"]] + [
        fields(v, {"sha256", "bytes"}, set(), "file receipt")["sha256"]
        for v in data["files"].values()
    ]:
        if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
            raise InputError("invalid SHA-256 receipt")
    for name, info in data["files"].items():
        relative(name)
        if type(info["bytes"]) is not int or info["bytes"] < 0:
            raise InputError("invalid receipt byte count")
    return data


def check(current: Snapshot, locked: dict) -> list[dict]:
    findings = [{"code": "uncovered", "path": p} for p in current.uncovered]
    if digest(canonical(current.manifest)) != locked["manifest_sha256"]:
        findings.append({"code": "manifest_changed"})
    for name in sorted(current.files.keys() | locked["files"].keys()):
        if name not in locked["files"]:
            code = "unlocked_file"
        elif name not in current.files:
            code = "removed_file"
        elif current.files[name] != locked["files"][name]:
            code = "bytes_changed"
        else:
            continue
        findings.append({"code": code, "path": name})
    return findings


def render(current: Snapshot) -> bytes:
    parts = [b"THIRD-PARTY NOTICES\nGenerated by notice-weave 0.1.0 from an explicit inventory.\n"]
    for c in current.manifest["components"]:
        header = (
            f"\n{'=' * 72}\n{c['name']} ({c['version']})\nID: {c['id']}\nSource: {c['source']}\n"
        )
        header += "Artifacts:\n" + "".join(f"  {p}\n" for p in c["artifacts"])
        parts.append(header.encode("utf-8"))
        for name in c["notices"]:
            raw = current.notices[name]
            parts.extend([f"\n--- {name} ---\n".encode(), raw])
            if not raw.endswith(b"\n"):
                parts.append(b"\n")
    return b"".join(parts)


def write_output(path: Path, data: bytes, protected: list[Path], force: bool) -> None:
    destination = path.resolve()
    if destination in {p.resolve() for p in protected}:
        raise InputError("output must not replace an input")
    if path.is_symlink() or (path.exists() and is_link(path.lstat())):
        raise InputError("output must not be a link or reparse point")
    if path.exists() and not force:
        raise InputError("output exists; use --force after reviewing the change")
    # Write completely before publishing. Exclusive hard-link creation preserves
    # no-clobber semantics if another writer creates the destination meanwhile.
    fd, temporary = tempfile.mkstemp(prefix=".notice-weave-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        if force:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
