---
name: annotate-merge-request
description: Annotate a merge request / pull request with reviewer-facing explanations of AI-authored changes - intent, before/after behavior, and a verified entry-point graph - posted as one overview comment plus a small number of inline comments on genuinely non-obvious code, and kept in sync after every push. Use this skill whenever the user wants to explain, document, annotate, or "self-describe" an MR/PR for reviewers, make an AI-generated MR reviewable without a Q&A round-trip, comment on a diff in GitLab/GitHub/Bitbucket, or refresh/re-check MR comments after pushing new commits - including phrasings like "explain this MR", "annotate the diff", "comment the PR for reviewers", or "update my MR comments".
license: MIT
metadata:
  author: Kirill Kolomin
  version: "1.0.0"
---

# Annotate a merge request for reviewers

A reviewer reading an AI-authored diff spends most of their time reconstructing three things the author already knew: *why* this change exists, *what behavior changed*, and *who calls this code*. This skill writes those three things down, in plain language, at the level of the merge request - not as source-code comments.

**The scarce resource is reviewer attention, not information.** A diff buried in forty explanatory comments is worse than an unannotated one. Every rule below exists to keep the annotation set small enough that a reviewer reads all of it.

## Operating modes

| Mode | When | What it does |
|---|---|---|
| `annotate` | First run on an MR | Builds the full annotation set, previews it, posts it after approval |
| `sync` | After every push to the MR branch | Re-checks existing annotations against the new diff; updates, removes, or adds only what changed |

If annotations from this skill already exist on the MR (detect by marker, see §7), **run `sync`, not `annotate`** - re-running `annotate` duplicates comments.

## 1. Preflight

Establish, before writing anything:

1. **Platform and MR identity.** `git remote -v` → gitlab.com/self-hosted GitLab, github.com, or Bitbucket. Then find the open MR for the current branch (`glab mr view`, `gh pr view`). If there is no MR yet, stop and say so - this skill annotates an existing MR; it does not create one.
2. **Diff range.** Always `git merge-base HEAD origin/<target-branch>` → `<base>..HEAD`. Never diff against the bare target branch tip: unrelated commits that landed on target would show up as this MR's changes.
3. **Language.** Write annotations in the language the project's MRs already use (check existing MR/PR descriptions and comments). Default to the language the user is speaking to you in.
4. **Authority to post.** Posting to an MR is visible to the whole team and notifies reviewers. Default to a **dry-run preview** in the conversation and post only after the user approves. Skip the preview only if the user has already said to post without asking.

Read `references/platform-gitlab.md`, `references/platform-github.md`, or `references/platform-bitbucket.md` for the exact commands - the comment APIs differ in ways that matter (anchoring, resolvability, update semantics).

## 2. Build the change inventory

```bash
python3 scripts/diff_inventory.py <base>..HEAD --json > /tmp/sdmr-inventory.json
```

This produces, per changed file: change kind (added/modified/deleted/renamed), hunks with **new-side line numbers** (what inline comments must anchor to), the nearest enclosing symbol per hunk, and size/triviality signals. It is a heuristic map for your reading, not a substitute for it - read the actual diff for anything you are going to describe.

Each hunk's `anchor` is a suggestion (its first added line); `added_lines` lists every line in that hunk you could anchor to instead. Pick the line the explanation is actually about.

**Hard constraint: an inline comment can only anchor to a line that appears in the diff.** Neither GitLab nor GitHub lets you comment on untouched code far from a hunk. Anything you want to say about code the MR did not touch goes in the overview comment (§4), never inline.

## 3. Decide what deserves an annotation

Run the significance test from `references/significance-test.md` on every candidate. The short version:

**Annotate when** the reader could reasonably ask "why is this like this?" - non-obvious intent, a behavioral change that is not visible in the diff, a non-local consequence, a deliberate trade-off, an unusual algorithm, a workaround, a constraint from outside the file, or an interaction with another change in this same MR.

**Skip when** the code explains itself to a competent reader of this codebase: a 5-10 line helper that title-cases a string, a `DEBOUNCE_MS = 300` constant, a rename, a formatting change, a mechanical test update, an obvious null check. A comment there costs attention and returns nothing.

The *size* of the code is not the test - its *inferential distance* is. A 6-line helper inside a custom encoding scheme needs a comment; a 200-line generated snapshot file does not.

**Budgets** (defaults; the user may raise them explicitly):

- At most **1 inline comment per file**, and at most **8 per MR**.
- Exceeding a budget is a signal, not a license: if more than 8 places in one MR are genuinely non-obvious, the MR is too large, or the explanation belongs in the overview comment where it can be told as one story. Say that to the user.

## 4. Draft the overview comment

One comment at MR level, the entry point for the whole review. Structure it exactly as `references/annotation-format.md` specifies. It carries:

- **Intent** - what problem this MR solves, in two or three sentences, in plain language. No restating the diff.
- **Before → after behavior** - what an observer of the running system would notice. For a new component, say "new" rather than inventing a "before".
- **Entry-point graph** - how a reader reaches the changed code from a real entry point (HTTP route, CLI command, event handler, cron, exported API). Bounded at 3 levels; a per-file map, not a call graph dump.
- **Reading order** - which file to open first, which are mechanical follow-through.
- **Index of inline comments** - links to each inline annotation, so the reviewer can see the whole annotation set from one place.

### Verifying the entry-point graph

**Never guess a call graph.** A fabricated caller list is worse than no annotation: it is confidently wrong and the reviewer will trust it. For each claimed edge, find the caller with an actual search (`rg -n 'symbolName'` across the repo, including tests and config), and follow it upward until you reach an entry point or 3 levels, whichever comes first. If a symbol's callers cannot be resolved - dynamic dispatch, DI container, reflection, a string-keyed registry - write `entry point unresolved (<reason>)` rather than a plausible-sounding chain.

## 5. Draft the inline comments

Each inline annotation uses the same three sections as the overview, scoped to that hunk, and stays short - a reviewer reads it inside a diff view. See `references/annotation-format.md` for the template, section-omission rules, and worked examples.

## 6. Cross-references within the MR

When a change only makes sense together with another change in the same MR, link them. Cross-references usually belong in the entry-point graph, but also appear in intent ("needed because <other file> now passes X") and before/after ("the old path still exists, see <other comment>").

**A comment URL does not exist until the comment is posted**, so cross-linking takes two phases:

1. Post every comment with a placeholder token (`[[ref:<slug>]]`) where a link to another annotation belongs.
2. Collect the created comments' ids/URLs, then edit each body, replacing tokens with real links.

Plan the slugs before posting - every `[[ref:...]]` token must resolve in phase 2, and a leftover token in a posted comment is a visible defect. Phase 2 is not optional.

## 7. Post, with an identity marker

Every comment this skill creates ends with a marker line that is invisible in rendered markdown:

```html
<!-- sdmr:v1 kind=overview|inline slug=<slug> anchor=<file>@<new-line> fp=<hunk-fingerprint> -->
```

The marker is what makes `sync` possible: it identifies the skill's own comments, what each one was attached to, and the fingerprint of the code it described. Never post an annotation without one; never edit a human's comment.

**Leave annotations unresolved.** A resolved thread renders collapsed, so the reviewer would have to expand every annotation one by one - which hides exactly what the annotation exists to show. Post them open and let the reviewer resolve each one as they read it; that click is their own "read it" marker.

The cost of that choice: where the project requires all threads resolved before merging (GitLab's *All threads must be resolved*, GitHub's *Require conversation resolution*), the annotations must be resolved before the merge button unblocks. That is one click per thread at the end, which is cheaper than expanding each one at the start - but **tell the user** when you detect such a setting, and offer to bulk-resolve them at the end if they'd rather. Commands for both are in the platform reference files.

## 8. Sync after every push

New commits silently invalidate annotations: the code a comment describes may have moved, changed meaning, or disappeared. Re-run this skill in `sync` mode after each push to the MR branch.

```bash
python3 scripts/sync_state.py --inventory /tmp/sdmr-inventory.json --comments /tmp/sdmr-comments.json
```

`--comments` is repeatable and takes the platform's raw JSON as-is - on GitHub that is two calls (review comments and issue comments), so pass both files.

It classifies every existing annotation as `ok` (anchor and fingerprint unchanged - leave it alone), `moved` (same code, new line - re-anchor), `stale` (code under the anchor changed - re-read and rewrite), or `orphaned` (file or hunk is gone - delete the comment, or replace its body with a one-line note if the platform cannot delete it). It also reports hunks that are now non-obvious and have no annotation yet.

Then: fix only what it flagged, always rewrite the overview comment in place (it summarizes the whole MR, so any push can invalidate it), and re-run phase 2 of §6 so cross-reference links still point at live comments. Follow `references/sync-after-push.md` - it covers the force-push case, deleted-comment handling per platform, and how to avoid churning comments that did not actually change.

Mention to the user, once, that this needs to run after each push, and that `references/sync-after-push.md` has an optional `pre-push` git hook if they want it automatic.

## 9. Report

Tell the user what was posted and what was deliberately left unannotated - the skipped-as-obvious list is how they calibrate the significance test. If you hit a budget, say which places lost out.

## Reference files

- `references/annotation-format.md` - exact structure of the overview and inline comments, with worked examples
- `references/significance-test.md` - annotate/skip decision rules and borderline cases
- `references/platform-gitlab.md` - `glab`/REST commands, diff position objects, non-blocking notes
- `references/platform-github.md` - `gh api` commands, line/side anchoring, outdated comments
- `references/platform-bitbucket.md` - Bitbucket mapping (**untested** - treat as a starting point)
- `references/sync-after-push.md` - staleness classification, force-push handling, optional git hook
- `scripts/diff_inventory.py` - parses a diff range into an annotatable inventory (JSON)
- `scripts/sync_state.py` - classifies existing annotations as ok/moved/stale/orphaned
