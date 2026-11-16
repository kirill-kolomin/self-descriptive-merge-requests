# Bitbucket (untested)

> **This mapping has not been tested against a live Bitbucket instance.** It is a starting point derived from Bitbucket's documented API shape, not verified behavior. Treat every command here as a hypothesis: run it on a throwaway PR first, and tell the user plainly that Bitbucket support is unverified before posting anything to a real PR.

Bitbucket calls them **pull requests** and uses a single comments endpoint for both PR-level and inline comments, distinguished by an `inline` object in the payload.

## Bitbucket Cloud

```bash
# PR-level comment
curl -sS -u "$BB_USER:$BB_APP_PASSWORD" \
  -X POST "https://api.bitbucket.org/2.0/repositories/$WORKSPACE/$REPO/pullrequests/$PR_ID/comments" \
  -H 'Content-Type: application/json' \
  -d '{"content": {"raw": "...markdown..."}}'

# inline comment
curl -sS -u "$BB_USER:$BB_APP_PASSWORD" \
  -X POST "https://api.bitbucket.org/2.0/repositories/$WORKSPACE/$REPO/pullrequests/$PR_ID/comments" \
  -H 'Content-Type: application/json' \
  -d '{"content": {"raw": "..."}, "inline": {"path": "src/pricing/service.ts", "to": 84}}'
```

- `inline.to` = line in the **new** file; `inline.from` = line in the old file (use for deletions).
- Update: `PUT .../comments/{comment_id}`; delete: `DELETE .../comments/{comment_id}`.
- List for sync: `GET .../comments?pagelen=100`, then filter on the `<!-- sdmr:v1` marker in `content.raw`.
- Permalinks: the response's `links.html.href`.

If `$BB_TOKEN` (access token) is in use instead of an app password, send `-H "Authorization: Bearer $BB_TOKEN"` instead of `-u`.

## Bitbucket Data Center / Server

Different API entirely (`/rest/api/1.0/...`), with comments posted to `.../pull-requests/{id}/comments` and anchors expressed as an `anchor` object (`path`, `line`, `lineType`, `fileType`). Comment updates require the current `version` field for optimistic locking - a blind `PUT` fails with 409. Verify against the instance's own API browser before use.

## Known gaps vs GitLab/GitHub

- **Resolution semantics differ** and are version-dependent; do not assume annotations are non-blocking. Check the repo's merge checks before posting a batch.
- **Outdated-comment behavior is unverified** - whether Bitbucket re-anchors or orphans a comment after a force-push is not established here, so `sync` must rely on the marker fingerprint rather than any platform "outdated" flag.
- **No official CLI equivalent to `gh`/`glab`**, so every call is raw `curl` with credentials from the environment. Never inline a token into a command the user can see echoed; read it from the environment.
