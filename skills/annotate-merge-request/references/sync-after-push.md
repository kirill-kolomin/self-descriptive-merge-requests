# Keeping annotations true after a push

An annotation is a claim about code. Every push can falsify it: the described line moves, its logic changes, the file disappears, or a new non-obvious hunk arrives with nothing explaining it. A stale annotation is worse than a missing one - the reviewer trusts it and reviews code that no longer exists.

**Run `sync` after every push to the MR branch.** Never re-run `annotate` on an MR that already has annotations - that duplicates them.

## The loop

1. `git fetch origin`, then recompute the diff range: `git merge-base HEAD origin/<target>`. The base **moves** when the target branch advances or the branch was rebased - reusing the old base makes the whole inventory wrong.
2. Rebuild the inventory: `python3 scripts/diff_inventory.py <base>..HEAD --json > /tmp/sdmr-inventory.json`.
3. Fetch this skill's own comments by marker into `/tmp/sdmr-comments.json` (commands in the platform reference for your host).
4. Classify: `python3 scripts/sync_state.py --inventory /tmp/sdmr-inventory.json --comments /tmp/sdmr-comments.json`.
5. Act on each class (below). Read the actual new code before rewriting any body - the classifier tells you *that* something changed, never *what it now means*.
6. Rewrite the overview comment in place; any push can invalidate its intent, behavior table, or entry-point graph.
7. Re-run the cross-reference pass (SKILL.md §6 phase 2) if any comment was deleted or reposted - its URL changed, and links to it in other comments are now dead.
8. Report: how many annotations were kept, updated, removed, added.

## Classes and what to do

| Class | Meaning | Action |
|---|---|---|
| `ok` | Anchor line and fingerprint both unchanged | **Nothing.** Do not re-post, do not "refresh". Untouched comments keep their URLs and the thread history reviewers have already read. |
| `moved` | Same code, different line number | Re-anchor. Prefer editing the existing comment if the platform still renders it correctly; repost only if it has become unanchored. |
| `stale` | Code under the anchor changed | Re-read the hunk, rewrite the body, edit in place. Update the `fp=` value in the marker. |
| `orphaned` | File or hunk no longer in the diff | Delete the comment. If deletion is not permitted, replace the body with one line: `Change described here was removed in a later push.` plus the marker. |
| `uncovered` | New hunk that passes the significance test, no annotation | Add one - subject to the same budgets (1/file, 8/MR). |

## Edit, don't churn

Prefer `PATCH`/`PUT` over delete-and-repost:

- Editing keeps the comment's URL, so cross-references and anything a reviewer bookmarked stay valid.
- Editing keeps replies. Deleting a comment a human replied to destroys their words - **never delete a comment that has replies**; edit the body instead.
- A reposted comment re-notifies every subscriber. A reviewer who gets eight notifications per push stops reading them.

And do not rewrite a body whose *meaning* is unchanged. If the only difference is phrasing, leave it. Measure against the fingerprint, not against whether you would word it the same way today.

## Resolved threads that went stale

A reviewer resolving an annotation means "I read this". If a later push makes that annotation `stale` or `moved`, the reviewer's acknowledgement no longer covers the code that is there now - so **unresolve the thread when you rewrite its body**, and say in the report which ones you reopened. Leaving a rewritten explanation collapsed under a resolved thread is how a reviewer ends up approving code nobody explained.

- GitLab: `PUT .../discussions/<discussion_id> -f resolved=false`
- GitHub: the `unresolveReviewThread` GraphQL mutation, same shape as `resolveReviewThread`

Do not touch the resolved state of an `ok` annotation.

## Force-push and rebase

After a force-push, the old commit SHAs are gone:

- GitLab diff notes keep pointing at dead SHAs and render as outdated with no way to re-anchor them. For `moved`/`stale` notes on GitLab after a force-push, delete and repost against the new `diff_refs` - unless the note has replies, in which case edit the body and leave the stale anchor, noting the move in the text.
- GitHub re-anchors review comments when it can and nulls `line`/`position` when it cannot. A null `line` after a force-push usually means repost.
- Always re-read `diff_refs` / `headRefOid` from the platform after a force-push; never reuse cached SHAs.

If the branch was rebased onto a new target, treat `uncovered` generously: hunks that were previously invisible (because they belonged to the old base) are now genuinely part of this MR.

## Fingerprints

The marker carries `fp=<hash>` - a hash of the normalized code the annotation describes (the anchored line plus its hunk context, with whitespace collapsed and comments stripped). `scripts/sync_state.py` recomputes it from the current diff and compares.

This is what separates "the line number moved" from "the code changed". Position checks alone cannot tell those apart, and a line can also keep both its number and its text while the function around it changes meaning - the fingerprint covers the enclosing hunk precisely so that case shows up as `stale`.

## Making it automatic (optional)

A git hook cannot run an agent conversation, but it can make the reminder impossible to miss. Opt-in only - install it only if the user asks:

```bash
cat > .git/hooks/pre-push <<'HOOK'
#!/bin/sh
# Remind that MR annotations need re-checking after this push.
printf '\n\033[33m[sdmr]\033[0m pushed - run the annotate-merge-request skill in sync mode to re-check MR comments.\n\n' >&2
exit 0
HOOK
chmod +x .git/hooks/pre-push
```

If the user's agent client has a non-interactive CLI, the same hook can invoke it directly (e.g. a headless prompt like `sync MR annotations`) - that is client-specific, so confirm the exact command with the user instead of guessing. Keep `exit 0` either way: an annotation step must never be able to block a push.
