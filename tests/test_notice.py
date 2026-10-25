import json
import os
import subprocess
import sys

import pytest

from notice_weave import core
from notice_weave.cli import main

MANIFEST = """version = 1
inventory_roots = ["vendor"]
[[components]]
id = "demo"
name = "Demo"
version = "1.0"
source = "https://example.invalid/demo"
artifacts = ["vendor/demo.js"]
notices = ["LICENSE.demo"]
"""


@pytest.fixture
def project(tmp_path):
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor/demo.js").write_bytes(b"export const answer = 42;\n")
    (tmp_path / "LICENSE.demo").write_bytes(b"Copyright demo\r\nPermission to test.\n")
    manifest = tmp_path / "notices.toml"
    manifest.write_text(MANIFEST, encoding="utf-8")
    return manifest


def test_end_to_end_installed_cli(project):
    root = project.parent
    lock = root / "notices.lock.json"
    bundle = root / "NOTICES.txt"

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "notice_weave", *map(str, args)], capture_output=True, text=True
        )

    assert run("lock", project, "--output", lock).returncode == 0
    assert run("render", project, "--lock", lock, "--output", bundle).returncode == 0
    good = run("check", project, "--lock", lock, "--bundle", bundle)
    assert good.returncode == 0, good.stderr
    assert json.loads(good.stdout)["ok"]
    assert (root / "LICENSE.demo").read_bytes() in bundle.read_bytes()
    (root / "vendor/unreviewed.js").write_bytes(b"new")
    bad = run("check", project, "--lock", lock)
    assert bad.returncode == 1
    assert json.loads(bad.stdout)["findings"] == [
        {"code": "uncovered", "path": "vendor/unreviewed.js"}
    ]


def test_receipt_detects_notice_and_asset_changes(project):
    old = core.snapshot(project)
    locked = old.lock()
    for path in ("LICENSE.demo", "vendor/demo.js"):
        (project.parent / path).write_bytes(b"changed\n")
    findings = core.check(core.snapshot(project), locked)
    assert {f["path"] for f in findings if f["code"] == "bytes_changed"} == {
        "LICENSE.demo",
        "vendor/demo.js",
    }


def test_semantic_manifest_pin_ignores_comments(project):
    lock = core.snapshot(project).lock()
    project.write_text("# comment\n" + MANIFEST, encoding="utf-8")
    assert core.check(core.snapshot(project), lock) == []
    project.write_text(MANIFEST.replace('version = "1.0"', 'version = "2.0"'), encoding="utf-8")
    assert core.check(core.snapshot(project), lock) == [{"code": "manifest_changed"}]


def test_bundle_stale_and_failed_render_leave_output(project, capsys):
    root = project.parent
    lock, output = root / "lock.json", root / "NOTICE.txt"
    assert main(["lock", str(project), "--output", str(lock)]) == 0
    output.write_bytes(b"stale")
    assert main(["check", str(project), "--lock", str(lock), "--bundle", str(output)]) == 1
    assert "bundle_stale" in capsys.readouterr().out
    (root / "vendor/demo.js").write_bytes(b"changed")
    assert (
        main(["render", str(project), "--lock", str(lock), "--output", str(output), "--force"]) == 1
    )
    assert output.read_bytes() == b"stale"


@pytest.mark.parametrize("path", ["../a", "/a", "a/../b", "a//b", "a\\b", "C:a", "a\n", ".", ""])
def test_reject_paths(path):
    with pytest.raises(core.InputError):
        core.relative(path)


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.replace("version = 1", "version = true"),
        lambda s: s + "\nunknown = 3\n",
        lambda s: s.replace('["vendor"]', '["vendor", "vendor/nested"]'),
        lambda s: s.replace('["vendor/demo.js"]', '["vendor/demo.js", "vendor/demo.js"]'),
        lambda s: s.replace('["vendor/demo.js"]', '["elsewhere.js"]'),
        lambda s: s.replace('name = "Demo"', 'name = ""'),
        lambda s: s.replace('notices = ["LICENSE.demo"]', "notices = []"),
        lambda s: s + s[s.index("[[components]]") :],
    ],
)
def test_reject_invalid_manifest(project, change):
    project.write_text(change(MANIFEST), encoding="utf-8")
    with pytest.raises(core.InputError):
        core.load_manifest(project)


def test_uncovered_prevents_lock(project):
    (project.parent / "vendor/.hidden").write_bytes(b"hidden")
    with pytest.raises(core.InputError, match="uncovered"):
        core.snapshot(project).lock()


@pytest.mark.parametrize("content", [b"", b" \n", b"\xff", b"a\x00b", b"a\x1bb"])
def test_reject_invalid_notices(project, content):
    (project.parent / "LICENSE.demo").write_bytes(content)
    with pytest.raises((ValueError, core.InputError)):
        core.snapshot(project)


def test_missing_input_returns_two(project):
    (project.parent / "LICENSE.demo").unlink()
    assert main(["lock", str(project), "--output", str(project.parent / "lock.json")]) == 2


def test_no_overwrite_input_or_existing(project):
    before = project.read_bytes()
    assert main(["lock", str(project), "--output", str(project), "--force"]) == 2
    assert project.read_bytes() == before
    output = project.parent / "out"
    core.write_output(output, b"one", [], False)
    with pytest.raises(core.InputError):
        core.write_output(output, b"two", [], False)
    assert output.read_bytes() == b"one"
    core.write_output(output, b"two", [], True)
    assert output.read_bytes() == b"two"
    assert not list(project.parent.glob(".notice-weave-*"))


def test_limits(project, monkeypatch):
    monkeypatch.setattr(core, "MAX_NOTICE", 2)
    with pytest.raises(core.InputError, match="exceeds"):
        core.snapshot(project)


def test_inventory_limit(project, monkeypatch):
    monkeypatch.setattr(core, "MAX_FILES", 1)
    with pytest.raises(core.InputError):
        core.snapshot(project)


def test_duplicate_lock_keys(project):
    path = project.parent / "lock.json"
    path.write_text('{"version":1,"version":1}')
    with pytest.raises(core.InputError, match="duplicate"):
        core.load_lock(path)


@pytest.mark.parametrize("bad", ["x", 3, None, True])
def test_invalid_receipt(project, bad):
    data = core.snapshot(project).lock()
    data["files"]["LICENSE.demo"]["sha256"] = bad
    path = project.parent / "lock.json"
    path.write_text(json.dumps(data))
    with pytest.raises(core.InputError):
        core.load_lock(path)


def test_symlink_rejected(project):
    target = project.parent / "vendor/link"
    try:
        os.symlink(project.parent / "LICENSE.demo", target)
    except OSError:
        pytest.skip("host does not grant symlink creation")
    with pytest.raises(core.InputError, match="links"):
        core.snapshot(project)


def test_nested_inventory_and_shared_notices(project):
    root = project.parent
    (root / "vendor/nested").mkdir()
    (root / "vendor/nested/second").write_bytes(b"second")
    project.write_text(
        MANIFEST
        + """
[[components]]
id = "second"
name = "Second"
version = "2"
source = "local"
artifacts = ["vendor/nested/second"]
notices = ["LICENSE.demo"]
"""
    )
    state = core.snapshot(project)
    assert not state.uncovered
    assert len(state.files) == 3
    assert core.render(state).count(b"Copyright demo") == 2


def test_added_removed_receipts(project):
    state = core.snapshot(project)
    locked = state.lock()
    locked["files"]["gone"] = locked["files"].pop("LICENSE.demo")
    assert core.check(state, locked) == [
        {"code": "unlocked_file", "path": "LICENSE.demo"},
        {"code": "removed_file", "path": "gone"},
    ]
