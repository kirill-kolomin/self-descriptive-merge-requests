# self-descriptive-merge-requests

An [Agent Plugin](https://agent-plugins.org/) that makes AI-authored merge requests explain themselves.

When an agent writes the code, the reviewer is the only person in the loop who does not know why anything is the way it is. So the review becomes an interrogation: *why this order? what did this change? who calls this? is this related to that other file?* - a round-trip per question, each one a context switch for both sides.

This plugin has the agent answer those questions **up front, on the merge request**, where review actually happens: a map of the change at MR level, plus short notes on the genuinely non-obvious lines. It works at the level of the merge request and the git client, not the source code - nothing here adds comments to your source files.

Once installed, ask your agent things like:

- "Annotate this MR for reviewers"
- "Explain this PR so nobody has to ask me why"
- "I pushed new commits - re-check the MR comments"

## Install

**Using the [skills CLI](https://skills.sh):**

```bash
npx skills add kirill-kolomin/self-descriptive-merge-requests
```

**Using GitHub CLI (Copilot, other `gh skill`-compatible clients):**

```bash
gh skill install kirill-kolomin/self-descriptive-merge-requests
```

**Manually, for any client:** clone this repo, then point your client at it the way it documents loading local plugins (most read from a plugins/extensions directory or a config file listing plugin paths).

## What it posts

### 1. One overview comment at MR level

The reviewer's entry point, carrying:

- **Intent** - what problem this MR solves and why this approach, in plain language.
- **Behavior: before → after** - what an observer of the running system would notice, including what is *not* changing but looks like it should be.
- **Entry points** - how the changed code is reached from a real entry point (HTTP route, CLI command, event handler, cron, exported API), bounded at three levels.
- **Reading order** - which file to open first, which are mechanical follow-through.
- **An index of the inline notes**, so the whole annotation set is visible from one place.

### 2. A few inline comments, only where the code is genuinely non-obvious

Each one anchored to a diff line, using the same three sections scoped to that hunk - three to six lines, readable inside a diff view:

```markdown
**Why:** Tax must be applied before rounding, otherwise each line item rounds twice
and invoices drift by up to a cent per item - the bug in #4412.

**Before → after:** Totals change by at most 1 cent on multi-item invoices; the stored
rounding mode is unchanged, so historical invoices are not affected.

**Reached from:** `POST /api/orders` → `OrderController.create` → `PricingService.quote`
```

### 3. Cross-references between changes in the same MR

When a change is only correct because of another change in the same MR, the annotations link to each other - usually in the entry-point graph, but also in intent ("needed because `TenantResolver` now returns per-tenant configs") and in before/after. Since a comment's URL does not exist until it is posted, the agent posts with placeholder tokens and then edits in the real links.

## When it stays quiet

The whole design rests on one judgment call: **most code does not need a comment.** A helper that title-cases each word in a string, or a `DEBOUNCE_MS = 300` constant, is already clear to anyone qualified to review it - a comment there spends the reviewer's attention and returns nothing. But a six-line helper inside a custom encoding scheme does need explaining, even though it is shorter.

The test is not the size of the code, it is the **inferential distance**: would a competent reviewer be left with a question that one sentence from the author would answer?

```js
// no comment - the name and body say everything
function titleCase(s) { /* ... */ }

// annotated - 6 lines, but you cannot tell whether it is correct
// without knowing which encoding contract it implements
function packHeader(flags, len) {
  return ((flags & 0x0f) << 12) | (len & 0x0fff);
}
```

Annotations are also skipped for renames, formatting, lockfiles and generated output, mechanical test updates, and idiomatic boilerplate. The full rule set, with borderline cases, is in [`skills/annotate-merge-request/references/significance-test.md`](skills/annotate-merge-request/references/significance-test.md).

## The main trade-off: comment noise

**The honest downside of this approach is that a merge request fills up with comments, and past some density that distracts more than it helps.** A diff buried in forty explanations is worse to review than a bare one - the reviewer starts skimming, and skims past the one comment that mattered.

Four things keep that in check:

1. **Overview first.** Anything that can be said once, at MR level, is said there - not repeated per file. Most of the explanation lives in one comment the reviewer reads top to bottom.
2. **Hard budgets.** At most 1 inline comment per file and 8 per MR, by default. You can raise them; the agent will not raise them on its own.
3. **The significance test above**, applied per hunk, with *skip* as the default answer.
4. **Budget pressure is a signal.** If more than 8 places in one MR are genuinely non-obvious, the finding is that the MR is too large to review well - and the agent says so instead of posting 30 comments.

Two further deliberate choices:

- **Annotations are posted unresolved.** A resolved thread renders collapsed, and expanding every annotation one by one costs more than it saves. The reviewer resolves each as they read it. Where a project requires all threads resolved before merging, the agent says so and offers to bulk-resolve at the end.
- **Annotations are not source-code comments.** They explain *this change* to *this reviewer* - information that belongs in the review, not in the codebase forever.

## Staying true after every push

New commits silently invalidate annotations: the described line moves, its logic changes, the file disappears, or a new non-obvious hunk arrives with nothing explaining it. **A stale annotation is worse than a missing one** - the reviewer trusts it and reviews code that is no longer there.

So the plugin has a second mode, run after every push, which re-checks each existing annotation against the new diff and classifies it:

| | | |
|---|---|---|
| `ok` | anchor and fingerprint unchanged | left completely alone |
| `moved` | same code, new line | re-anchored |
| `stale` | code under the anchor changed | re-read and rewritten in place |
| `orphaned` | file or hunk is gone | removed |
| `uncovered` | new hunk, no annotation | annotated if it passes the significance test |

Comments are edited rather than deleted and reposted, so their URLs, cross-reference links and reviewer replies survive. A comment a human replied to is never deleted. A resolved annotation that goes stale is reopened, since the reviewer's "I read this" no longer covers the code that is there now.

Each comment carries an invisible marker (`<!-- sdmr:v1 ... -->`) holding its anchor and a fingerprint of the code it describes. That is what makes the agent's own comments identifiable, and what distinguishes "the line number moved" from "the code changed".

## Platform support

| Platform | Status |
|---|---|
| **GitLab** (MRs, `glab`) | Supported. Overview via the Notes API, inline via the Discussions API with a `position` object. |
| **GitHub** (PRs, `gh`) | Supported. Overview via issue comments, inline via review comments with `line`/`side`. |
| **Bitbucket** | **Untested.** A documented mapping is included and may well work, but it has not been run against a live instance - the agent will tell you so before posting. |

The agent detects the platform from the git remote and finds the open MR for the current branch. It defaults to showing you a **dry-run preview** in the conversation and posts only after you approve.

## What it is not

- **Not a code review.** It explains; it does not approve, praise, or critique. If the agent finds a defect while annotating, it tells you in conversation and fixes it - it does not post a comment presenting a bug as intent.
- **Not a call-graph guesser.** Every edge in the entry-point graph is verified by searching the repo. Chains that cannot be resolved - dynamic dispatch, DI containers, string-keyed registries - are marked `entry point unresolved`, because a fabricated caller list is confidently wrong and the reviewer will trust it.

## Included scripts

Both are plain Python 3 with no dependencies and can be run on their own:

```bash
# map a diff range into the hunks an inline comment could anchor to
python3 skills/annotate-merge-request/scripts/diff_inventory.py \
    "$(git merge-base HEAD origin/main)..HEAD"

# classify existing annotations against the current diff
python3 skills/annotate-merge-request/scripts/sync_state.py \
    --inventory inventory.json --comments comments.json
```

`sync_state.py` accepts the raw comments JSON from any of the three platforms.

## Conformance

Conforms to the [Agent Plugins Specification v1.0.0](https://agent-plugins.org/specification). To check:

```bash
python3 <path-to>/agent-plugin-builder/skills/build-agent-plugin/scripts/validate_plugin.py .
```

## License

MIT - see `LICENSE`.
