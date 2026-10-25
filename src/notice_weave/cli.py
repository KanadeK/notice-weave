"""Command line entry point."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import (
    MAX_TOTAL,
    InputError,
    check,
    load_lock,
    read_limited,
    render,
    snapshot,
    write_output,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pin and bundle an explicit third-party inventory."
    )
    parser.add_argument("--version", action="version", version=__version__)
    subs = parser.add_subparsers(dest="command", required=True)
    for command in ("lock", "check", "render"):
        sub = subs.add_parser(command)
        sub.add_argument("manifest", type=Path)
        if command != "lock":
            sub.add_argument("--lock", required=True, type=Path)
        if command == "check":
            sub.add_argument("--bundle", type=Path, help="also verify this generated bundle")
        else:
            sub.add_argument("--output", required=True, type=Path)
            sub.add_argument("--force", action="store_true", help="replace an existing output")
    args = parser.parse_args(argv)
    try:
        current = snapshot(args.manifest)
        protected = [args.manifest] + [args.manifest.resolve().parent / p for p in current.files]
        if args.command == "lock":
            data = (json.dumps(current.lock(), indent=2, sort_keys=True) + "\n").encode()
            write_output(args.output, data, protected, args.force)
            result = {"ok": True, "files": len(current.files), "operation": "lock"}
        else:
            locked = load_lock(args.lock)
            findings = check(current, locked)
            if args.command == "check" and args.bundle:
                if read_limited(args.bundle, MAX_TOTAL) != render(current):
                    findings.append({"code": "bundle_stale"})
            if args.command == "render" and not findings:
                write_output(args.output, render(current), protected + [args.lock], args.force)
            result = {"ok": not findings, "files": len(current.files), "findings": findings}
        print(json.dumps(result, sort_keys=True, ensure_ascii=True))
        return 0 if result["ok"] else 1
    except (InputError, OSError, ValueError, RecursionError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
