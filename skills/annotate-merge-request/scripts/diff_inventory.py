#!/usr/bin/env python3
"""Turn a git diff range into an annotatable inventory.

Reads a unified diff (from a git range, or from stdin/a file) and emits, per
changed file, the hunks an inline merge-request comment could anchor to: their
new-side line numbers, the nearest enclosing symbol, size and triviality
signals, and a stable fingerprint of the change itself.

The fingerprint is what `sync_state.py` later compares against, so the two
scripts must agree on it - that is why it lives here and is imported there.

Usage:
    python3 diff_inventory.py <base>..<head> [--json]
    python3 diff_inventory.py --diff-file path/to.diff [--json]
    git diff base..head | python3 diff_inventory.py --stdin --json

Nothing here decides what deserves a comment; that judgment is the skill's
(see references/significance-test.md). This only maps the ground.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys

# ---------------------------------------------------------------- fingerprint

_COMMENT_PREFIXES = ("//", "#", "--", "/*", "*/", "*", '"""', "'''", ";", "%")


def _normalize_line(marker: str, text: str) -> str | None:
    """Normalize one diff line for fingerprinting, or drop it (None).

    Whitespace is collapsed and comment-only lines are dropped so that
    reformatting and comment edits do not report a change in meaning.
    """
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith(_COMMENT_PREFIXES):
        return None
    collapsed = re.sub(r"\s+", " ", stripped)
    return f"{marker}{collapsed}"


def hunk_fingerprint(lines: list[str]) -> str:
    """Fingerprint a hunk from its raw diff body lines (with +/-/space markers).

    Both sides are included: an annotation describes a transition, so a change
    to the removed side changes what "before" means.
    """
    normalized = []
    for raw in lines:
        if not raw:
            continue
        marker, text = raw[0], raw[1:]
        if marker not in "+- ":
            continue
        norm = _normalize_line(marker if marker != " " else "=", text)
        if norm is not None:
            normalized.append(norm)
    payload = "\n".join(normalized).encode("utf-8", "replace")
    return hashlib.sha1(payload).hexdigest()[:12]


# ------------------------------------------------------------------- signals

GENERATED_PATTERNS = (
    r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|composer\.lock|Gemfile\.lock|go\.sum)$",
    r"(^|/)(dist|build|out|vendor|node_modules|\.next|coverage)/",
    r"\.(min\.js|min\.css|map|snap|lock|pb\.go|pb2\.py|g\.dart|generated\.ts)$",
    r"(^|/)__snapshots__/",
    r"(^|/)(migrations?|_migrations)/",
)

TEST_PATTERNS = (
    r"(^|/)(tests?|__tests__|spec|specs|e2e)/",
    r"[._-](test|spec)\.[a-z0-9]+$",
    r"(^|/)test_[^/]+\.py$",
    r"[^/]+_test\.(go|py|rb|js|ts)$",
)

SYMBOL_RE = re.compile(
    r"""^\s*(?:
        (?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(?P<fn>[A-Za-z_$][\w$]*)
      | (?:export\s+)?(?:abstract\s+)?class\s+(?P<cls>[A-Za-z_$][\w$]*)
      | def\s+(?P<pydef>[A-Za-z_][\w]*)
      | (?:public|private|protected|internal|static|\s)*(?:func|fn|sub|method)\s+(?P<gofn>[A-Za-z_][\w]*)
      | (?:const|let|var)\s+(?P<arrow>[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?\(
      | (?P<method>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::[^{;]+)?\{\s*$
    )""",
    re.VERBOSE,
)


def _matches_any(path: str, patterns) -> bool:
    return any(re.search(p, path) for p in patterns)


def _enclosing_symbol(section_heading: str, body: list[str], anchor_index: int) -> str | None:
    """Best-effort nearest enclosing symbol for a hunk.

    Prefers git's own section heading (filled in by git's language-aware diff
    drivers), then falls back to scanning upwards from the anchor line - the
    nearest definition *above* the anchor, not merely anywhere in the hunk.
    """
    above = [l[1:] for l in body[: anchor_index + 1] if l[:1] in " +-"]
    for candidate in (section_heading, *reversed(above)):
        if not candidate:
            continue
        m = SYMBOL_RE.match(candidate)
        if m:
            name = next((v for v in m.groupdict().values() if v), None)
            if name and name not in ("if", "for", "while", "switch", "catch", "return"):
                return name
    heading = section_heading.strip()
    return heading or None


# --------------------------------------------------------------- diff parsing

HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@ ?(?P<heading>.*)$"
)


def parse_diff(diff_text: str) -> list[dict]:
    files: list[dict] = []
    current: dict | None = None
    hunk: dict | None = None
    new_line = old_line = 0

    def close_hunk():
        nonlocal hunk
        if current is not None and hunk is not None:
            _finalize_hunk(current, hunk)
            current["hunks"].append(hunk)
        hunk = None

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            close_hunk()
            current = _new_file_entry(raw)
            files.append(current)
            continue
        if current is None:
            continue
        if raw.startswith("new file mode"):
            current["change"] = "added"
        elif raw.startswith("deleted file mode"):
            current["change"] = "deleted"
        elif raw.startswith("rename from "):
            current["change"] = "renamed"
            current["old_path"] = raw[len("rename from "):].strip()
        elif raw.startswith("rename to "):
            current["change"] = "renamed"
            current["new_path"] = raw[len("rename to "):].strip()
        elif raw.startswith("Binary files") or raw.startswith("GIT binary patch"):
            current["binary"] = True
        elif raw.startswith("--- "):
            p = raw[4:].strip()
            current["old_path"] = None if p == "/dev/null" else _strip_prefix(p)
        elif raw.startswith("+++ "):
            p = raw[4:].strip()
            current["new_path"] = None if p == "/dev/null" else _strip_prefix(p)
        elif raw.startswith("@@"):
            m = HUNK_RE.match(raw)
            if not m:
                continue
            close_hunk()
            old_line = int(m.group("old_start"))
            new_line = int(m.group("new_start"))
            hunk = {
                "old_start": old_line,
                "old_count": int(m.group("old_count") or 1),
                "new_start": new_line,
                "new_count": int(m.group("new_count") or 1),
                "section_heading": (m.group("heading") or "").strip(),
                "body": [],
                "added": 0,
                "removed": 0,
                "anchor_new_line": None,
                "anchor_old_line": None,
                "anchor_index": 0,
                "added_lines": [],
            }
        elif hunk is not None and raw[:1] in "+- ":
            hunk["body"].append(raw)
            marker = raw[0]
            if marker == "+":
                hunk["added"] += 1
                hunk["added_lines"].append(new_line)
                if hunk["anchor_new_line"] is None:
                    hunk["anchor_new_line"] = new_line
                    hunk["anchor_index"] = len(hunk["body"]) - 1
                new_line += 1
            elif marker == "-":
                hunk["removed"] += 1
                if hunk["anchor_old_line"] is None:
                    hunk["anchor_old_line"] = old_line
                old_line += 1
            else:
                new_line += 1
                old_line += 1
        elif raw.startswith("\\ No newline"):
            continue

    close_hunk()
    for f in files:
        _finalize_file(f)
    return files


def _strip_prefix(path: str) -> str:
    for prefix in ("a/", "b/"):
        if path.startswith(prefix):
            return path[len(prefix):]
    return path


def _new_file_entry(header_line: str) -> dict:
    parts = header_line.split(" ")
    old_path = _strip_prefix(parts[2]) if len(parts) > 3 else None
    new_path = _strip_prefix(parts[3]) if len(parts) > 3 else None
    return {
        "old_path": old_path,
        "new_path": new_path,
        "change": "modified",
        "binary": False,
        "hunks": [],
    }


def _finalize_hunk(file_entry: dict, hunk: dict) -> None:
    hunk["fingerprint"] = hunk_fingerprint(hunk["body"])
    hunk["symbol"] = _enclosing_symbol(
        hunk["section_heading"], hunk["body"], hunk["anchor_index"]
    )
    changed = [l for l in hunk["body"] if l[:1] in "+-"]
    hunk["whitespace_only"] = bool(changed) and _is_whitespace_only(changed)
    if hunk["anchor_new_line"] is None:
        hunk["anchor_new_line"] = hunk["new_start"]
        hunk["anchor_side"] = "LEFT" if hunk["removed"] else "RIGHT"
    else:
        hunk["anchor_side"] = "RIGHT"
    path = file_entry.get("new_path") or file_entry.get("old_path") or ""
    hunk["anchor"] = f"{path}@{hunk['anchor_new_line']}"
    hunk["body"] = hunk["body"] if len(hunk["body"]) <= 80 else hunk["body"][:80] + ["... truncated ..."]


def _is_whitespace_only(changed_lines: list[str]) -> bool:
    added = sorted(re.sub(r"\s+", "", l[1:]) for l in changed_lines if l[0] == "+")
    removed = sorted(re.sub(r"\s+", "", l[1:]) for l in changed_lines if l[0] == "-")
    return added == removed


def _finalize_file(f: dict) -> None:
    path = f.get("new_path") or f.get("old_path") or ""
    f["path"] = path
    f["added"] = sum(h["added"] for h in f["hunks"])
    f["removed"] = sum(h["removed"] for h in f["hunks"])
    f["generated"] = _matches_any(path, GENERATED_PATTERNS)
    f["test"] = _matches_any(path, TEST_PATTERNS)
    f["whitespace_only"] = bool(f["hunks"]) and all(h["whitespace_only"] for h in f["hunks"])
    reasons = []
    if f["generated"]:
        reasons.append("generated-or-vendored")
    if f["whitespace_only"]:
        reasons.append("whitespace-only")
    if f["binary"]:
        reasons.append("binary")
    if f["test"]:
        reasons.append("test-file")
    if f["change"] == "renamed" and not f["hunks"]:
        reasons.append("pure-rename")
    f["likely_trivial"] = bool(reasons) and not (f["test"] and len(reasons) == 1 and f["added"] > 40)
    f["trivial_reasons"] = reasons
    # Every changed file needs a file-level comment except autogenerated ones.
    # "Trivial" only lowers how much that comment has to say; it never removes it.
    f["requires_file_comment"] = not f["generated"]
    f["file_fingerprint"] = hashlib.sha1(
        ("|".join(h["fingerprint"] for h in f["hunks"]) or path).encode("utf-8", "replace")
    ).hexdigest()[:12]


# ----------------------------------------------------------------------- main


def read_diff(args) -> str:
    if args.stdin:
        return sys.stdin.read()
    if args.diff_file:
        with open(args.diff_file, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    cmd = [
        "git", "diff", "--unified=3", "--find-renames",
        "--no-color", "--no-ext-diff", args.range,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        sys.exit(proc.returncode)
    return proc.stdout


def render_text(inventory: dict) -> str:
    out = [f"range: {inventory['range']}", ""]
    for f in inventory["files"]:
        flags = ",".join(f["trivial_reasons"]) or "-"
        coverage = "file-comment REQUIRED" if f["requires_file_comment"] else "exempt (autogenerated)"
        out.append(
            f"{f['change']:9} {f['path']}  +{f['added']}/-{f['removed']}  "
            f"hunks={len(f['hunks'])}  ffp={f['file_fingerprint']}  {coverage} [{flags}]"
        )
        for h in f["hunks"]:
            sym = h["symbol"] or "?"
            out.append(
                f"    {h['anchor']:50} side={h['anchor_side']:5} symbol={sym:28} "
                f"fp={h['fingerprint']} +{h['added']}/-{h['removed']}"
                + ("  (whitespace-only)" if h["whitespace_only"] else "")
            )
            if len(h["added_lines"]) > 1:
                shown = ",".join(str(n) for n in h["added_lines"][:12])
                more = ",..." if len(h["added_lines"]) > 12 else ""
                out.append(f"        anchorable new-side lines: {shown}{more}"
            )
        out.append("")
    t = inventory["totals"]
    out.append(
        f"totals: {t['files']} files, {t['hunks']} hunks, "
        f"+{t['added']}/-{t['removed']}, {t['trivial_files']} likely-trivial files"
    )
    out.append(
        f"coverage: {t['files_requiring_comment']} files need a file-level comment, "
        f"{t['files'] - t['files_requiring_comment']} exempt as autogenerated"
    )
    out.append("Inline (method/hunk) comments are selective: at most 3 per file, 12 per MR (defaults).")
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("range", nargs="?", help="git diff range, e.g. $(git merge-base HEAD origin/main)..HEAD")
    p.add_argument("--diff-file", help="read a unified diff from this file instead of running git")
    p.add_argument("--stdin", action="store_true", help="read a unified diff from stdin")
    p.add_argument("--json", action="store_true", help="emit JSON instead of a text summary")
    args = p.parse_args(argv)

    if not (args.range or args.diff_file or args.stdin):
        p.error("give a diff range, --diff-file, or --stdin")

    files = parse_diff(read_diff(args))
    inventory = {
        "range": args.range or args.diff_file or "<stdin>",
        "files": files,
        "totals": {
            "files": len(files),
            "hunks": sum(len(f["hunks"]) for f in files),
            "added": sum(f["added"] for f in files),
            "removed": sum(f["removed"] for f in files),
            "trivial_files": sum(1 for f in files if f["likely_trivial"]),
            "files_requiring_comment": sum(1 for f in files if f["requires_file_comment"]),
        },
    }
    print(json.dumps(inventory, indent=2) if args.json else render_text(inventory))
    return 0


if __name__ == "__main__":
    sys.exit(main())
