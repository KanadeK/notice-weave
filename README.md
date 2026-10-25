# notice-weave

Pin the third-party files you ship and generate a repeatable notice bundle.
Useful for manually vendored JavaScript, fonts, data and small libraries that
do not appear in your package manager's dependency graph.

Given a TOML inventory, notice-weave checks that every file under the declared
vendor directories is accounted for, hashes the assets and notices, and builds
a plain UTF-8 bundle. CI can detect a changed asset, changed notice, unreviewed
new file, changed component metadata or stale generated bundle. Everything runs
locally; source URLs are reference text and are never fetched.

## Install

Python 3.11+; no runtime dependencies. From a release source checkout:

```sh
git clone https://github.com/KanadeK/notice-weave.git
cd notice-weave
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
notice-weave --version
```

The distribution is published as GitHub release assets, not on PyPI. A downloaded
wheel can also be installed with `python -m pip install path/to/file.whl`.
Uninstall with `python -m pip uninstall notice-weave`; generated files are yours
to keep or delete. The tool has no daemon, database or user-level configuration.

## Try the complete workflow

```sh
notice-weave lock examples/notices.toml --output examples/notices.lock.json
notice-weave render examples/notices.toml --lock examples/notices.lock.json --output examples/THIRD_PARTY_NOTICES.txt
notice-weave check examples/notices.toml --lock examples/notices.lock.json --bundle examples/THIRD_PARTY_NOTICES.txt
```

The bundled example is authored demonstration data, not a real upstream
dependency. Edit its asset or add a file below `examples/vendor/`; the check
will fail. Restore the example afterward. Locking records the current bytes:
review the source and applicable license yourself **before** accepting a lock
update. Commit the manifest, lock and generated bundle with your project.
Use `--force` explicitly to replace an existing generated file.

## Manifest

Paths are relative to the manifest's directory, with `/` separators. Exact paths
are intentional; no glob expansion or automatic discovery of license names.

```toml
version = 1
inventory_roots = ["vendor"]

[[components]]
id = "example-widget"
name = "Example Widget"
version = "1.2.0"
source = "https://example.org/widget"
artifacts = ["vendor/widget.js"]
notices = ["legal/widget-LICENSE", "legal/widget-NOTICE"]
```

Every component needs all six fields and at least one artifact and notice.
Every regular file below the roots, including hidden files, must be declared
as an artifact or notice. Artifacts belong to exactly one component and must be
under a root. Notices can be shared and can live elsewhere within the manifest
directory. Root directories must not overlap. Unknown fields, duplicate IDs,
duplicate paths, absolute paths, parent traversal, symlinks, junctions and other
reparse points fail explicitly. There are no silent exclusions.

The lock contains SHA-256 and byte counts for all declared files, plus a hash of
normalized component metadata. Comments and TOML ordering do not change the
metadata hash; asset bytes, line endings and notice bytes do. Notices must be
nonempty UTF-8 text. Their bytes are preserved inside the bundle, with headings
and a separating newline where necessary. Identical notices are repeated for
each component so attribution is not silently merged.

## CI and output

After installing the tool, add this read-only command to your build:

```sh
notice-weave check notices.toml --lock notices.lock.json --bundle THIRD_PARTY_NOTICES.txt
```

All successful operations and audit findings are JSON on stdout. Diagnostics are
JSON on stderr. Exit codes: `0` verified/written, `1` drift or uncovered files,
`2` invalid/missing/unreadable input, limit violation, or failed output write.
A stale bundle emits `bundle_stale`. A failed render does not replace output.
Output publication uses a temporary file in the destination directory and atomic
replacement; no-overwrite mode uses an exclusive hard link (unsupported
filesystems return an error). Parent directories must already exist.

Python API: `notice_weave.core.snapshot(Path(...))`, `load_lock(Path(...))`,
`check(snapshot, lock)` and `render(snapshot)`. Call `check` before rendering;
the CLI enforces this order. API stability is provisional in 0.1.x.

## Boundaries

This checks an explicit inventory, not dependency completeness or legal
compatibility. It cannot establish ownership, permission or that a selected
notice is sufficient. It does not inspect release archives, infer package
versions, execute build scripts, or download anything. Pair it with your
ecosystem's dependency/license tools and include the generated bundle in the
actual release packaging.

Inputs must be a trusted, quiescent local tree. It detects ordinary concurrent
file changes, but is not a defense against adversarial filesystem races. Limits:
2 MiB manifest, 4 MiB per notice, 256 MiB per asset, 1 GiB total input bytes and
100,000 declared/scanned entries. Large inputs fail rather than being truncated.
Reports include your relative file names; bundles include full notice text.

## Development and alternatives

`python -m pip install -e ".[dev]"`, `pytest`, `ruff check .`,
`ruff format --check .`, `python -m build`.

[Licensed](https://github.com/licensee/licensed) handles license metadata for
supported dependency sources. [make-notices](https://github.com/katharostech/make-notices)
targets cargo and pnpm. This tool's scope is the explicitly inventoried files
outside those package-manager flows. See [DESIGN.md](DESIGN.md) and
[THIRD_PARTY.md](THIRD_PARTY.md). MIT licensed.

## 中文说明

用于手工放入项目的第三方 JS、字体、数据等资源。清单明确列出资产和声明文件；
工具检查是否遗漏目录中的文件，锁定全部文件的 SHA-256，生成可重复的声明文本，
并在 CI 中发现资产、声明或生成结果的变化。无需联网、无运行时依赖。

安装后按上面的三个命令依次执行 lock、render、check。更新 lock 只是记录当前字节，
应先人工核实来源和许可证。它不会判断法律合规，不会猜测未登记的依赖。
退出码 0 表示成功，1 表示发现差异，2 表示输入或运行错误。卸载使用
`python -m pip uninstall notice-weave`。
