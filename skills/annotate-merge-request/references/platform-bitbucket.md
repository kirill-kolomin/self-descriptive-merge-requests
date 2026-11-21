# Bitbucket (untested)

> **This mapping has not been tested against a live Bitbucket instance.** It is a starting point derived from Bitbucket's documented API shape, not verified behavior. Treat every command here as a hypothesis: run it on a throwaway PR first, and tell the user plainly that Bitbucket support is unverified before posting anything to a real PR.

Bitbucket calls them **pull requests**. Include an `inline` object on all Cloud annotations so they appear in the diff, including the summary on the first changed file in the reading order.

## Bitbucket Cloud

```bash
# inline comment
curl -sS -u "$BB_USER:$BB_APP_PASSWORD" \
  -X POST "https://api.bitbucket.org/2.0/repositories/$WORKSPACE/$REPO/pullrequests/$PR_ID/comments" \
  -H 'Content-Type: application/json' \
  -d '{"content": {"raw": "..."}, "inline": {"path": "src/pricing/service.ts", "to": 84}}'
```

- `inline.to` = line in the **new** file; `inline.from` = line in the old file (use for deletions).
- **File-level comments** (which this skill needs for every changed file) are documented as an `inline` object with only `path` and no line - but that is exactly the kind of detail this unverified mapping may have wrong. Try it on a throwaway PR; if it is rejected, fall back to anchoring on the file's first changed line.
- Update: `PUT .../comments/{comment_id}`; delete: `DELETE .../comments/{comment_id}`.
- List for sync: `GET .../comments?pagelen=100`, then filter on the `<!-- sdmr:v1` marker in `content.raw`.
- Use only a verified target line link in the PR diff. If one is unavailable, name the file and symbol without linking to the commit's source view or the comment response's `links.html.href`.

If `$BB_TOKEN` (access token) is in use instead of an app password, send `-H "Authorization: Bearer $BB_TOKEN"` instead of `-u`.

## Bitbucket Data Center / Server

Different API entirely (`/rest/api/1.0/...`), with comments posted to `.../pull-requests/{id}/comments` and anchors expressed as an `anchor` object (`path`, `line`, `lineType`, `fileType`). Use a diff anchor for every annotation, including the summary. Comment updates require the current `version` field for optimistic locking - a blind `PUT` fails with 409. Verify against the instance's own API browser before use.

## Known gaps vs GitLab/GitHub

- **Resolution semantics differ** and are version-dependent; do not assume annotations are non-blocking. Check the repo's merge checks before posting a batch.
- **Outdated-comment behavior is unverified** - whether Bitbucket re-anchors or orphans a comment after a force-push is not established here, so `sync` must rely on the marker fingerprint rather than any platform "outdated" flag.
- **No official CLI equivalent to `gh`/`glab`**, so every call is raw `curl` with credentials from the environment. Never inline a token into a command the user can see echoed; read it from the environment.
