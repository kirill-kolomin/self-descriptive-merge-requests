# GitHub

Verified against the GitHub REST API docs (Pulls / Comments, Issues / Comments) as of 2026-11.

Use `gh` (`gh auth status` to confirm). `gh api` handles auth, pagination (`--paginate`), and `{owner}/{repo}` substitution.

GitHub says "pull request" where this skill says "merge request" - same thing. Post all annotations via the Pulls API so they appear in Files changed.

## Find the PR and the diff range

```bash
gh pr view --json number,headRefName,baseRefName,headRefOid,url
git fetch origin && git merge-base HEAD origin/main
```

`headRefOid` is the PR's current head SHA - use it as `commit_id` when posting inline comments, not local `HEAD` (which may include unpushed commits).

## Summary in Files changed

Post `overview.md` with the file-level command below, using the first changed file in the reading order and retaining the `kind=overview` marker. Use the same changed-line fallback if needed. Do not use `gh pr comment` or the Issues API for new annotations.

To retire a legacy Conversation-only comment during migration:

```bash
gh api repos/{owner}/{repo}/issues/comments/<comment_id> -X PATCH -F body=@overview.md
gh api repos/{owner}/{repo}/issues/comments/<comment_id> -X DELETE
```

Note the path: issue comments are addressed as `issues/comments/<id>` (no PR number) for update/delete.

## File-level comment (mandatory coverage)

Every changed file needs one. Use `subject_type=file` and omit `line`:

```bash
gh api repos/{owner}/{repo}/pulls/<number>/comments -X POST \
  -F body=@file-note.md \
  -f commit_id=$HEAD_SHA \
  -f path=src/pricing/service.ts \
  -f subject_type=file
```

The comment attaches to the file header in the Files-changed view rather than to a code line, so it is the first thing a reviewer sees on opening the file and it does not interleave with the diff.

For a **deleted** file, `path` is still the deleted path and `subject_type=file` works; do not try to anchor a line. If `subject_type=file` is rejected (older GitHub Enterprise), fall back to a `line` anchor on the file's first changed line with `side=RIGHT` (or `LEFT` for a deletion), and say so in your report.

## Inline comment (review comment)

```bash
gh api repos/{owner}/{repo}/pulls/<number>/comments -X POST \
  -F body=@note.md \
  -f commit_id=$HEAD_SHA \
  -f path=src/pricing/service.ts \
  -F line=84 \
  -f side=RIGHT
```

| Parameter | Rule |
|---|---|
| `commit_id` | The PR's current head SHA. An older SHA renders the comment outdated as soon as a later commit touches the line. |
| `path` | Repo-relative path, new side |
| `line` | Line number in the **new** file; required unless `subject_type=file` |
| `side` | `RIGHT` for added/context lines, `LEFT` for deleted lines |
| `start_line`/`start_side` | Multi-line ranges only; prefer single lines |
| `subject_type` | `file` for a whole-file comment (then omit `line`) |

Do not use the legacy `position` parameter - it is being retired in favor of `line`.

Update and delete:

```bash
gh api repos/{owner}/{repo}/pulls/comments/<comment_id> -X PATCH -F body=@note.md
gh api repos/{owner}/{repo}/pulls/comments/<comment_id> -X DELETE
```

Posting each comment with its own POST (rather than one batched review) is deliberate: individual comments can be edited and deleted one at a time during `sync`, and they do not add a review verdict to the PR.

## Conversation resolution can block merge

If the branch has *Require conversation resolution before merging* enabled, every unresolved review-comment thread blocks the merge - so inline annotations become merge blockers.

Resolving is GraphQL-only (no REST endpoint):

```bash
# thread ids for the PR
gh api graphql -f query='
  query($owner:String!,$repo:String!,$num:Int!){
    repository(owner:$owner,name:$repo){
      pullRequest(number:$num){
        reviewThreads(first:100){ nodes { id isResolved isOutdated
          comments(first:1){ nodes { id databaseId body } } } } } } }' \
  -f owner=OWNER -f repo=REPO -F num=<number>

gh api graphql -f query='
  mutation($id:ID!){ resolveReviewThread(input:{threadId:$id}){ thread { isResolved } } }' \
  -f id=<thread_node_id>
```

**Do not resolve annotations as you post them.** A resolved thread renders collapsed, so the reviewer would have to expand each annotation to read it - the opposite of the point. Post them open.

Instead, check the setting and disclose the consequence:

```bash
gh api repos/{owner}/{repo}/branches/<base-branch>/protection \
  | jq '.required_conversation_resolution.enabled'   # needs admin; 404 if unprotected
```

If it is on (or you cannot read it), tell the user that the annotations will need resolving before merge, and offer the bulk-resolve above as a final step once the review is done. Never resolve a thread a human has replied to.

## Find this skill's own comments (for sync)

```bash
gh api repos/{owner}/{repo}/pulls/<number>/comments --paginate \
  | jq -s 'add // []' \
  > /tmp/sdmr-comments.json

# Also check for legacy Conversation-only annotations.
gh api repos/{owner}/{repo}/issues/<number>/comments --paginate \
  | jq -s 'add // []' \
  > /tmp/sdmr-overview.json
```

Keep unmarked replies in the fetched JSON so sync can detect them. Match annotations by the `<!-- sdmr:v1` marker, not by author.

## Diff-line links

Copy the target line link from Files changed. Verify that it opens the PR diff at that line, not a repository file or the thread URL from the comment response's `html_url`.

## Staleness signals

- For line comments, `line` and `position` become `null` when the anchored line no longer exists in the latest diff. Treat null `line` as `orphaned-or-moved` only for line comments, not for `subject_type=file`.
- `commit_id` older than the PR's current `headRefOid` means the comment was anchored to a previous revision; it may still render fine if the line was untouched.
- A comment can stay perfectly anchored while the code around it changed meaning. Position checks are necessary but not sufficient - use the marker fingerprint (`references/sync-after-push.md`).
