#!/usr/bin/env python3
"""Classify existing merge-request annotations against the current diff.

Answers one question per annotation this skill previously posted: is it still
true of the code? It compares the `anchor=` and `fp=` values carried in each
comment's `<!-- sdmr:v1 ... -->` marker against a fresh inventory from
`diff_inventory.py`.

    ok        anchor and fingerprint unchanged      -> leave it alone
    moved     same code, different line             -> re-anchor
    stale     code under the anchor changed         -> re-read and rewrite
    orphaned  file or hunk no longer in the diff    -> delete (or note removal)

It also lists hunks that now have no annotation (`uncovered`) and defects in
the posted comments (leftover cross-reference tokens, duplicate slugs,
malformed markers).

Usage:
    python3 sync_state.py --inventory inv.json --comments gitlab-or-github.json [...]
    python3 sync_state.py --inventory inv.json --comments gh-review.json --comments gh-issue.json --json

The comments file may be the raw JSON from either platform (a list of GitHub
review comments, GitLab discussions with nested notes, or Bitbucket's
`{"values": [...]}` page) - the walker finds comment objects wherever they sit.

This script decides nothing about *content*: `stale` means the code changed,
not that the new wording is known. Read the code before rewriting a body.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from diff_inventory import hunk_fingerprint  # noqa: E402  (shared fingerprint)

MARKER_RE = re.compile(r"<!--\s*sdmr:v1\s+(?P<attrs>.*?)-->", re.DOTALL)
ATTR_RE = re.compile(r"(\w+)=([^\s]+)")
REF_TOKEN_RE = re.compile(r"\[\[ref:([a-z0-9-]+)\]\]")


# --------------------------------------------------------------- comment walk


def _body_of(node: dict) -> str | None:
    """Comment text, whichever key this platform uses."""
    body = node.get("body")
    if isinstance(body, str):
        return body
    content = node.get("content")
    if isinstance(content, dict) and isinstance(content.get("raw"), str):
        return content["raw"]  # Bitbucket
    return None


def _url_of(node: dict) -> str | None:
    for key in ("html_url", "web_url", "url"):
        value = node.get(key)
        if isinstance(value, str):
            return value
    links = node.get("links")
    if isinstance(links, dict):
        html = links.get("html")
        if isinstance(html, dict) and isinstance(html.get("href"), str):
            return html["href"]  # Bitbucket
    return None


def _anchor_of(node: dict) -> tuple[str | None, int | None]:
    """Platform-reported anchor: (path, new-side line), either may be None."""
    position = node.get("position")
    inline = node.get("inline")
    path = node.get("path")
    line = node.get("line")
    if isinstance(position, dict):  # GitLab
        path = path or position.get("new_path") or position.get("old_path")
        if line is None:
            line = position.get("new_line")
    if isinstance(inline, dict):  # Bitbucket
        path = path or inline.get("path")
        if line is None:
            line = inline.get("to")
    return path, line


def _author_of(node: dict) -> str | None:
    for key in ("author", "user"):
        value = node.get(key)
        if isinstance(value, dict):
            return value.get("username") or value.get("login") or value.get("display_name")
    return None


def walk_comments(node, parent_discussion=None, found=None):
    """Collect comment-like objects from any platform's JSON shape.

    GitHub returns a flat list, GitLab nests notes inside discussions, and
    Bitbucket wraps pages in `values`. Rather than branch per platform, walk
    the whole tree and keep every object that has an id and a comment body.
    """
    if found is None:
        found = []
    if isinstance(node, dict):
        body = _body_of(node)
        if body is not None and node.get("id") is not None:
            path, line = _anchor_of(node)
            found.append(
                {
                    "id": node.get("id"),
                    "discussion_id": parent_discussion,
                    "body": body,
                    "url": _url_of(node),
                    "path": path,
                    "line": line,
                    "original_line": node.get("original_line"),
                    "in_reply_to_id": node.get("in_reply_to_id"),
                    "author": _author_of(node),
                    "resolved": node.get("resolved"),
                }
            )
        # a dict holding `notes` is a GitLab discussion: its id groups the notes
        discussion_id = (
            node.get("id") if isinstance(node.get("notes"), list) else None
        ) or node.get("discussion_id") or parent_discussion
        for key, value in node.items():
            if key in ("body", "content"):
                continue
            walk_comments(value, discussion_id, found)
    elif isinstance(node, list):
        for item in node:
            walk_comments(item, parent_discussion, found)
    return found


def parse_marker(body: str) -> dict | None:
    m = MARKER_RE.search(body)
    if not m:
        return None
    return dict(ATTR_RE.findall(m.group("attrs")))


def split_anchor(anchor: str) -> tuple[str | None, int | None]:
    if not anchor or "@" not in anchor:
        return (anchor or None, None)
    path, _, line = anchor.rpartition("@")
    try:
        return path, int(line)
    except ValueError:
        return path, None


# ------------------------------------------------------------- classification


def build_index(inventory: dict):
    by_fingerprint: dict[str, list[dict]] = {}
    by_path: dict[str, list[dict]] = {}
    files: dict[str, dict] = {}
    for f in inventory.get("files", []):
        files[f.get("path")] = {
            "path": f.get("path"),
            "change": f.get("change"),
            "file_fingerprint": f.get("file_fingerprint"),
            "requires_file_comment": f.get("requires_file_comment", True),
            "generated": f.get("generated"),
            "likely_trivial": f.get("likely_trivial"),
            "trivial_reasons": f.get("trivial_reasons", []),
            "added": f.get("added"),
            "removed": f.get("removed"),
        }
        for h in f.get("hunks", []):
            entry = {
                "path": f.get("path"),
                "change": f.get("change"),
                "likely_trivial": f.get("likely_trivial"),
                "trivial_reasons": f.get("trivial_reasons", []),
                "anchor": h.get("anchor"),
                "anchor_new_line": h.get("anchor_new_line"),
                "anchor_side": h.get("anchor_side"),
                "fingerprint": h.get("fingerprint"),
                "symbol": h.get("symbol"),
                "whitespace_only": h.get("whitespace_only"),
                "added_lines": h.get("added_lines", []),
                "new_start": h.get("new_start"),
                "new_count": h.get("new_count"),
            }
            by_fingerprint.setdefault(entry["fingerprint"], []).append(entry)
            by_path.setdefault(entry["path"], []).append(entry)
    return by_fingerprint, by_path, files


def covers_line(hunk: dict, line: int) -> bool:
    start = hunk.get("new_start") or 0
    return start <= line < start + (hunk.get("new_count") or 1)


def classify(comment: dict, marker: dict, by_fingerprint, by_path, files) -> dict:
    kind = marker.get("kind", "inline")
    path, line = split_anchor(marker.get("anchor", ""))
    fp = marker.get("fp")
    result = {
        "comment_id": comment["id"],
        "discussion_id": comment.get("discussion_id"),
        "url": comment.get("url"),
        "kind": kind,
        "slug": marker.get("slug"),
        "anchor_path": path,
        "anchor_line": line,
        "fingerprint": fp,
        "has_replies": comment.get("has_replies", False),
        "platform_line": comment.get("line"),
    }

    if kind == "overview":
        result["class"] = "overview"
        result["anchor_path"] = comment.get("path")
        result["anchor_line"] = comment.get("line")
        result["action"] = (
            "refresh the summary and verify its current diff anchor"
            if result["anchor_path"]
            else "verify placement and migrate to Changes if unanchored"
        )
        return result

    if kind == "file":
        # File-level comments are mandatory coverage, so they are keyed to the
        # file as a whole: their fingerprint is over every hunk in the file.
        file_path = path or marker.get("anchor")
        result["anchor_path"] = file_path
        entry = files.get(file_path)
        if entry is None:
            result["class"] = "orphaned"
            result["action"] = (
                "file is no longer in the diff - delete the file comment "
                "(if it has replies, edit the body to say the file is no longer touched)"
            )
            return result
        expected = marker.get("ffp") or fp
        if expected and expected == entry["file_fingerprint"]:
            result["class"] = "ok"
            result["action"] = "no change - do not repost or refresh"
        else:
            result["class"] = "stale"
            result["action"] = (
                f"the file's changes moved on (ffp {expected or '?'} -> "
                f"{entry['file_fingerprint']}) - re-read the file's diff, rewrite the body, "
                "update ffp= in the marker"
            )
        return result

    if not path or not fp:
        result["class"] = "unknown"
        result["action"] = "marker is missing anchor= or fp=; re-read the comment and repost it with a full marker"
        return result

    matches = [h for h in by_fingerprint.get(fp, []) if h["path"] == path]
    if matches:
        hunk = matches[0]
        result["current_line"] = hunk["anchor_new_line"]
        result["symbol"] = hunk["symbol"]
        if line is not None and hunk["anchor_new_line"] == line:
            result["class"] = "ok"
            result["action"] = "no change - do not repost or refresh"
        else:
            result["class"] = "moved"
            result["action"] = (
                f"re-anchor to {hunk['anchor']} (side {hunk['anchor_side']}); "
                "body text is still accurate"
            )
        return result

    hunks = by_path.get(path, [])
    if not hunks:
        result["class"] = "orphaned"
        result["action"] = (
            "file is no longer in the diff - delete the comment "
            "(if it has replies, edit the body to say the change was removed)"
        )
        return result

    nearby = [h for h in hunks if line is not None and covers_line(h, line)]
    candidates = nearby or sorted(
        hunks, key=lambda h: abs((h.get("anchor_new_line") or 0) - (line or 0))
    )[:2]
    result["class"] = "stale"
    result["candidates"] = [
        {"anchor": h["anchor"], "fingerprint": h["fingerprint"], "symbol": h["symbol"]}
        for h in candidates
    ]
    result["action"] = (
        "code under this anchor changed - re-read the hunk, rewrite the body, "
        "update fp= in the marker"
    )
    return result


def file_coverage(files, annotations):
    """Which changed files still lack their mandatory file-level comment."""
    annotated = {
        a.get("anchor_path")
        for a in annotations
        if a.get("kind") == "file" and a.get("class") != "orphaned"
    }
    rows = []
    for path, entry in files.items():
        if not entry["requires_file_comment"]:
            state = "exempt"
        elif path in annotated:
            state = "covered"
        else:
            state = "MISSING"
        rows.append(
            {
                "path": path,
                "state": state,
                "change": entry["change"],
                "file_fingerprint": entry["file_fingerprint"],
                "trivial_reasons": entry["trivial_reasons"],
                "added": entry["added"],
                "removed": entry["removed"],
            }
        )
    return sorted(rows, key=lambda r: ({"MISSING": 0, "covered": 1, "exempt": 2}[r["state"]], r["path"]))


def find_uncovered(by_path, annotations, include_trivial=False):
    claimed = {
        (a.get("anchor_path"), a.get("fingerprint"))
        for a in annotations
        if a.get("kind") == "inline"
    }
    claimed_fps = {fp for _, fp in claimed}
    out = []
    for path, hunks in by_path.items():
        for h in hunks:
            if h["fingerprint"] in claimed_fps:
                continue
            if h["whitespace_only"]:
                continue
            if h["likely_trivial"] and not include_trivial:
                continue
            out.append(
                {
                    "anchor": h["anchor"],
                    "fingerprint": h["fingerprint"],
                    "symbol": h["symbol"],
                    "side": h["anchor_side"],
                    "change": h["change"],
                    "trivial_reasons": h["trivial_reasons"],
                }
            )
    return out


def find_defects(marked, annotations):
    defects = []
    slugs: dict[str, list] = {}
    for comment, marker in marked:
        for token in REF_TOKEN_RE.findall(comment["body"]):
            defects.append(
                {
                    "comment_id": comment["id"],
                    "defect": "unresolved cross-reference token",
                    "detail": f"[[ref:{token}]] is still in the posted body - "
                    "replace it with a verified code-line link",
                }
            )
        slug = marker.get("slug")
        if slug:
            slugs.setdefault(slug, []).append(comment["id"])
    for slug, ids in slugs.items():
        if len(ids) > 1:
            defects.append(
                {
                    "comment_id": ids[0],
                    "defect": "duplicate slug",
                    "detail": f"slug '{slug}' is used by comments {ids} - annotation identity is ambiguous",
                }
            )
    overviews = [a for a in annotations if a["kind"] == "overview"]
    if len(overviews) > 1:
        defects.append(
            {
                "comment_id": overviews[0]["comment_id"],
                "defect": "multiple overview comments",
                "detail": f"{len(overviews)} overview comments found - keep one in the current diff "
                "and retire the rest without deleting reviewer replies",
            }
        )
    return defects


# ----------------------------------------------------------------------- main


def render_text(report: dict) -> str:
    order = {"stale": 0, "orphaned": 1, "moved": 2, "unknown": 3, "overview": 4, "ok": 5}
    out = ["== annotations =="]
    for a in sorted(report["annotations"], key=lambda a: order.get(a["class"], 9)):
        head = f"[{a['class']:8}] #{a['comment_id']} {a.get('anchor_path') or '(mr level)'}"
        if a.get("anchor_line"):
            head += f"@{a['anchor_line']}"
        if a.get("slug"):
            head += f"  slug={a['slug']}"
        out.append(head)
        out.append(f"           -> {a['action']}")
        for c in a.get("candidates", []):
            out.append(f"           candidate: {c['anchor']} fp={c['fingerprint']} symbol={c['symbol'] or '?'}")
        if a.get("has_replies"):
            out.append("           NOTE: has replies - never delete; edit the body instead")
    if not report["annotations"]:
        out.append("(none found - this MR has no annotations from this skill; run annotate, not sync)")

    out.append("")
    out.append("== file coverage (every changed file needs a file-level comment unless autogenerated) ==")
    for r in report["file_coverage"]:
        flags = ",".join(r["trivial_reasons"]) or "-"
        line = (
            f"  [{r['state']:7}] {r['path']:50} {r['change']:9} "
            f"+{r['added']}/-{r['removed']} ffp={r['file_fingerprint']} [{flags}]"
        )
        out.append(line)
    out.append("")
    out.append("== uncovered hunks (candidates - apply the significance test, do not annotate blindly) ==")
    for u in report["uncovered"]:
        out.append(f"  {u['anchor']:50} side={u['side']:5} symbol={u['symbol'] or '?':24} fp={u['fingerprint']}")
    if not report["uncovered"]:
        out.append("  (none)")

    if report["defects"]:
        out.append("")
        out.append("== defects ==")
        for d in report["defects"]:
            out.append(f"  #{d['comment_id']}: {d['defect']} - {d['detail']}")

    s = report["summary"]
    inline_live = sum(
        1 for a in report["annotations"]
        if a["kind"] == "inline" and a["class"] in ("ok", "moved", "stale")
    )
    out.append("")
    out.append("summary: " + (", ".join(f"{k}={v}" for k, v in s.items() if v) or "nothing found"))
    out.append(f"inline budget in use: {inline_live}/12 (max 3 per file)")
    if s.get("files_missing_comment"):
        out.append(
            f"ACTION: {s['files_missing_comment']} changed file(s) have no file-level comment yet"
        )
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--inventory", required=True, help="JSON from diff_inventory.py --json")
    p.add_argument("--comments", required=True, action="append",
                   help="platform JSON with the MR's comments (repeatable)")
    p.add_argument("--include-trivial", action="store_true",
                   help="also list likely-trivial hunks as uncovered candidates")
    p.add_argument("--json", action="store_true", help="emit JSON instead of a text report")
    args = p.parse_args(argv)

    with open(args.inventory, encoding="utf-8") as fh:
        inventory = json.load(fh)

    all_comments = []
    for path in args.comments:
        with open(path, encoding="utf-8") as fh:
            all_comments.extend(walk_comments(json.load(fh)))

    reply_targets = {c["in_reply_to_id"] for c in all_comments if c.get("in_reply_to_id")}
    discussion_sizes: dict = {}
    for c in all_comments:
        if c.get("discussion_id"):
            discussion_sizes[c["discussion_id"]] = discussion_sizes.get(c["discussion_id"], 0) + 1
    for c in all_comments:
        c["has_replies"] = c["id"] in reply_targets or discussion_sizes.get(c.get("discussion_id"), 0) > 1

    marked = [(c, m) for c in all_comments if (m := parse_marker(c["body"])) is not None]

    by_fingerprint, by_path, files = build_index(inventory)
    annotations = [classify(c, m, by_fingerprint, by_path, files) for c, m in marked]
    coverage = file_coverage(files, annotations)

    summary: dict[str, int] = {}
    for a in annotations:
        summary[a["class"]] = summary.get(a["class"], 0) + 1

    report = {
        "range": inventory.get("range"),
        "annotations": annotations,
        "file_coverage": coverage,
        "uncovered": find_uncovered(by_path, annotations, args.include_trivial),
        "defects": find_defects(marked, annotations),
        "summary": summary,
    }
    report["summary"]["files_missing_comment"] = sum(1 for r in coverage if r["state"] == "MISSING")
    report["summary"]["uncovered_hunks"] = len(report["uncovered"])
    report["summary"]["defects"] = len(report["defects"])

    print(json.dumps(report, indent=2) if args.json else render_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
