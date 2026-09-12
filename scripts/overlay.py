"""Compose, check and sync a deployment overlay. Standard library only, so it runs anywhere.

A deployment repository is the upstream repository with a private overlay laid on top, kept
current by merging upstream's main. The one rule that keeps that merge conflict-free is that the
overlay only adds files; `overlay.cfg` declares the paths it owns.

    overlay.py check                       refuse a contract violation, on either side
    overlay.py compose --overlay DIR --out DIR [--ref main]
    overlay.py sync [--ref main]           in a composed repository: merge upstream

`check` decides which side it is on by the presence of `.overlay/`, which the overlay owns. On
the upstream side it refuses any declared overlay path that exists. On the deployment side it
refuses a missing overlay path, an upstream-owned file that differs from upstream, and a
site identifier (patterns in `.overlay/forbidden.txt`) anywhere outside the overlay paths.
"""

from __future__ import annotations

import argparse
import configparser
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

CONFIG = "overlay.cfg"
MARKER = ".overlay"
FORBIDDEN = ".overlay/forbidden.txt"


class Contract:
    def __init__(self, root: Path) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(root / CONFIG)
        section = cfg["overlay"]
        self.root = root
        self.upstream = section["upstream"].strip()
        self.paths = [p.strip() for p in section["paths"].splitlines() if p.strip()]

    def owns(self, relpath: str) -> bool:
        for p in self.paths:
            if p.endswith("/"):
                if relpath == p.rstrip("/") or relpath.startswith(p):
                    return True
            elif relpath == p or fnmatch.fnmatch(relpath, p):
                return True
        return False


def _identity(root: Path) -> list[str]:
    """A committer identity when the environment has none, as a pipeline runner often has not.

    Supplied only when nothing is configured, so a repository or a job that sets its own keeps it.
    """
    probe = subprocess.run(
        ["git", "-C", str(root), "config", "user.email"], text=True, capture_output=True
    )
    if probe.stdout.strip():
        return []
    return ["-c", "user.name=overlay tool", "-c", "user.email=overlay@noreply.invalid"]


def _git(
    root: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *_identity(root), *args],
        text=True,
        capture_output=True,
        check=check,
    )


def _tracked(root: Path) -> list[str]:
    return _git(root, "ls-files").stdout.split()


def check(root: Path) -> int:
    contract = Contract(root)
    problems: list[str] = []
    downstream = (root / MARKER).is_dir()
    tracked = _tracked(root)
    if not downstream:
        present = [f for f in tracked if contract.owns(f)]
        problems += [f"overlay-owned path exists upstream: {f}" for f in present]
    else:
        for p in contract.paths:
            if not (root / p.rstrip("/")).exists():
                problems.append(f"overlay path missing: {p}")
        forbidden = _patterns(root)
        for f in tracked:
            if contract.owns(f):
                continue
            data = (root / f).read_bytes()
            if b"\0" in data:
                continue
            text = data.decode("utf-8", errors="replace")
            for pat in forbidden:
                if pat.search(text):
                    problems.append(f"site identifier in an upstream-owned file: {f}")
                    break
        problems += _edited_upstream_files(root, contract)
    side = "deployment" if downstream else "upstream"
    if problems:
        print(f"overlay contract violated on the {side} side:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(
        f"overlay contract holds on the {side} side ({len(contract.paths)} owned paths)"
    )
    return 0


def _patterns(root: Path) -> list[re.Pattern[str]]:
    f = root / FORBIDDEN
    if not f.exists():
        return []
    lines = [ln.strip() for ln in f.read_text().splitlines()]
    return [re.compile(ln) for ln in lines if ln and not ln.startswith("#")]


def _edited_upstream_files(root: Path, contract: Contract) -> list[str]:
    """Upstream-owned files the deployment side has changed since the last upstream merge.

    The last merged upstream commit is recorded as the ref `refs/overlay/upstream` by `sync`
    and `compose`. Without it there is nothing to compare against and the check is skipped
    rather than passed vacuously; it says so.
    """
    base = _git(
        root, "rev-parse", "--verify", "-q", "refs/overlay/upstream", check=False
    )
    if base.returncode != 0:
        print(
            "note: no recorded upstream ref; edited-file check skipped", file=sys.stderr
        )
        return []
    diff = _git(root, "diff", "--name-only", base.stdout.strip(), "HEAD").stdout.split()
    return [
        f"upstream-owned file edited on the deployment side: {f}"
        for f in diff
        if not Contract(root).owns(f)
    ]


def compose(overlay: Path, out: Path, ref: str, upstream: str | None) -> int:
    contract_src = overlay / CONFIG
    url = upstream or (Contract(overlay).upstream if contract_src.exists() else None)
    if url is None:
        print(
            "compose: pass --upstream, or keep an overlay.cfg beside the overlay",
            file=sys.stderr,
        )
        return 2
    subprocess.run(["git", "clone", "-q", "--branch", ref, url, str(out)], check=True)
    _git(out, "update-ref", "refs/overlay/upstream", "HEAD")
    for f in _tracked(overlay):
        dst = out / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((overlay / f).read_bytes())
    _git(out, "add", "-A")
    _git(out, "commit", "-q", "-m", "chore(overlay): apply the deployment overlay")
    return check(out)


def sync(root: Path, ref: str) -> int:
    contract = Contract(root)
    _git(root, "fetch", "-q", contract.upstream, ref)
    merge = _git(root, "merge", "--no-ff", "--no-edit", "FETCH_HEAD", check=False)
    if merge.returncode != 0:
        conflicts = _git(root, "diff", "--name-only", "--diff-filter=U").stdout.split()
        print("sync: merge conflict", file=sys.stderr)
        for f in conflicts:
            why = (
                "overlay-owned path now also exists upstream"
                if contract.owns(f)
                else "edited on both sides"
            )
            print(f"  {f}: {why}", file=sys.stderr)
        _git(root, "merge", "--abort", check=False)
        return 1
    _git(root, "update-ref", "refs/overlay/upstream", "FETCH_HEAD")
    print(
        f"sync: merged upstream {ref} ({_git(root, 'rev-parse', '--short', 'FETCH_HEAD').stdout.strip()})"
    )
    return check(root)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--root", default=".")
    p = sub.add_parser("compose")
    p.add_argument("--overlay", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--ref", default="main")
    p.add_argument("--upstream")
    s = sub.add_parser("sync")
    s.add_argument("--root", default=".")
    s.add_argument("--ref", default="main")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        return check(Path(a.root).resolve())
    if a.cmd == "compose":
        return compose(
            Path(a.overlay).resolve(), Path(a.out).resolve(), a.ref, a.upstream
        )
    return sync(Path(a.root).resolve(), a.ref)


if __name__ == "__main__":
    raise SystemExit(main())
