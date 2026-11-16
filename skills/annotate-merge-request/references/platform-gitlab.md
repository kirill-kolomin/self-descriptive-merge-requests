# GitLab

Verified against the GitLab REST API docs (Notes API, Discussions API) as of 2026-11.

Use `glab` when it is installed and authenticated (`glab auth status`); fall back to `curl` with `$GITLAB_TOKEN` against `$CI_API_V4_URL` / `https://gitlab.com/api/v4`. `glab api` proxies the REST API with auth already handled, which is the most reliable path:

```bash
glab api projects/:id/merge_requests/:iid/notes -X POST -f body="..."
```

`:id` may be the URL-encoded path (`group%2Fproject`); `glab api` substitutes `:id` for the current repo automatically. `:iid` is the MR's **internal** id (the number in the MR URL), not the global `id`.

## Find the MR and the diff range

```bash
glab mr view --output json           # iid, source/target branch, sha, diff_refs
git fetch origin
git merge-base HEAD origin/main      # the base for `git diff`
```

Always take the SHAs for comment positions from the MR itself, not from local git:

```bash
glab api projects/:id/merge_requests/:iid | jq '.diff_refs'
# → { "base_sha": "...", "head_sha": "...", "start_sha": "..." }
```

`diff_refs` is the authoritative source for `position[*_sha]`. Local `HEAD` can differ from the MR head (unpushed commits), and a mismatched `head_sha` makes the position invalid - the API rejects it with `400 Note {:line_code=>["must be a valid line code"]}`.

## Overview comment (MR level)

```bash
glab api projects/:id/merge_requests/:iid/notes -X POST --field body="$(cat overview.md)"
```

Notes created this way are **not** attached to a line and are **not** resolvable threads - exactly what the overview comment needs. `POST .../notes` does not accept a `position` parameter at all; it cannot create inline comments.

Update and delete:

```bash
glab api projects/:id/merge_requests/:iid/notes/<note_id> -X PUT --field body="$(cat overview.md)"
glab api projects/:id/merge_requests/:iid/notes/<note_id> -X DELETE
```

## Inline comment (diff level)

Only the Discussions API can anchor to a line:

```bash
glab api projects/:id/merge_requests/:iid/discussions -X POST \
  --field body="$(cat note.md)" \
  -f position[position_type]=text \
  -f position[base_sha]=$BASE_SHA \
  -f position[start_sha]=$START_SHA \
  -f position[head_sha]=$HEAD_SHA \
  -f position[new_path]=src/pricing/service.ts \
  -f position[old_path]=src/pricing/service.ts \
  -f position[new_line]=84
```

### File-level comment (mandatory coverage)

Every changed file needs one. Use `position_type=file` and send no line numbers:

```bash
glab api projects/:id/merge_requests/:iid/discussions -X POST \
  --field body="$(cat file-note.md)" \
  -f position[position_type]=file \
  -f position[base_sha]=$BASE_SHA \
  -f position[start_sha]=$START_SHA \
  -f position[head_sha]=$HEAD_SHA \
  -f position[new_path]=src/pricing/service.ts \
  -f position[old_path]=src/pricing/service.ts
```

For a deleted file send `old_path` only; for an added file, `new_path` only (send both for anything else, including renames, where they differ).

`position_type=file` needs a reasonably recent GitLab. If the instance rejects it (`400`, or an "invalid position" error), fall back to a `text` position on the file's **first changed line** - the body is unchanged, only the anchor is worse. Note the fallback in your report so the user knows why some comments sit on a line.

### Line-level comment

Line selection rules:

| Target line | Send |
|---|---|
| Added line | `new_line` only (omit `old_line`) |
| Removed line | `old_line` only (omit `new_line`) |
| Unchanged context line | **both** `new_line` and `old_line` |

`new_path` and `old_path` are both required for `position_type=text`; for a renamed file they differ. 

Multi-line annotations use `position[line_range][start]` / `[end]`. Prefer a single line - a range is harder to keep valid across pushes for no reviewer benefit.

## Resolvable threads: leave them open

**This is the one GitLab-specific trap.** Every diff comment is a thread, and threads are resolvable; there is no API flag to create a non-resolvable diff note. So each annotation is, mechanically, an open thread.

**Leave them open anyway.** A resolved thread renders collapsed - the reviewer would have to click open every annotation before reading it, which costs more attention than the annotation saves. Open threads are visible at a glance, and the reviewer resolving one is a natural "I've read this".

The trade-off to disclose: if the project has *All threads must be resolved* enabled, open annotations hold the merge until someone resolves them. Check it and say so:

```bash
glab api projects/:id | jq '.only_allow_merge_if_all_discussions_are_resolved'
```

If it is `true`, tell the user: the annotations will need resolving before merge - one click each at the end, or offer to bulk-resolve when the review is done:

```bash
# only at the end, and only if the user asks for it
glab api "projects/:id/merge_requests/:iid/discussions?per_page=100" --paginate \
  | jq -r '.[] | select(.notes[0].body | contains("<!-- sdmr:v1")) | select(.notes[0].resolvable) | .id' \
  | while read -r d; do
      glab api "projects/:id/merge_requests/:iid/discussions/$d" -X PUT -f resolved=true
    done
```

Resolving needs the Developer role or above, or authorship of the change under review. Never resolve a thread that has replies from a human - that closes their open question.

## Find this skill's own comments (for sync)

```bash
glab api "projects/:id/merge_requests/:iid/discussions?per_page=100" --paginate \
  | jq '[.[] | {discussion_id: .id, individual_note,
                notes: [.notes[] | select(.body | contains("<!-- sdmr:v1"))
                        | {id, body, position, resolved, author: .author.username}]}]
      | map(select(.notes | length > 0))' > /tmp/sdmr-comments.json
```

The discussions listing includes individual notes too (`individual_note: true`), so this one call finds both the overview comment and the inline ones. Match on the `<!-- sdmr:v1` marker - never on author alone, since the same account posts human comments too.

Edit a note inside a thread:

```bash
glab api projects/:id/merge_requests/:iid/discussions/<discussion_id>/notes/<note_id> -X PUT -f body="..."
glab api projects/:id/merge_requests/:iid/discussions/<discussion_id>/notes/<note_id> -X DELETE
```

Send either `body` or `resolved` in one call, never both.

## Comment permalinks (for cross-references)

`https://<host>/<group>/<project>/-/merge_requests/<iid>#note_<note_id>`

The note id comes back in the POST response (`.id`, or `.notes[0].id` for a discussion). Collect them all, then run phase 2 of the cross-reference pass.

## Staleness signals

- A diff note whose code changed in a later push shows as **outdated** in the UI; the note's `position` keeps pointing at the old SHAs.
- Compare `position.head_sha` against the MR's current `diff_refs.head_sha`: different → the annotation was anchored to an older revision and needs re-checking.
- `position` alone is not enough to tell whether the *meaning* changed. Use the fingerprint in the marker (`references/sync-after-push.md`).
