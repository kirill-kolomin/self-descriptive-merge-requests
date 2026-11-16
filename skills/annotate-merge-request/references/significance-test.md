# The significance test

Apply this to every candidate anchor before writing anything. The default answer is **skip** - an annotation must earn its place against the reviewer's attention.

## The one question

> Reading only the diff and knowing this codebase, would a competent reviewer be left with a question that a sentence from the author would answer?

If no - skip. If yes - annotate, and make the annotation answer *that* question.

## Annotate when any of these holds

| Trigger | Example |
|---|---|
| **Non-obvious intent** | An ordering, a guard, or a cast that looks arbitrary but is load-bearing |
| **Invisible behavior change** | The diff looks like a refactor but changes what the system does |
| **Non-local consequence** | A change here alters behavior in a file the MR does not touch |
| **Deliberate trade-off** | A slower-but-correct path, a deliberate duplication, a narrowed scope |
| **Unusual algorithm or encoding** | Custom serialization, bit manipulation, hand-rolled parsing, retry/backoff math |
| **Workaround** | Driven by an upstream bug, an API quirk, a platform limitation, a deadline |
| **External constraint** | A protocol, a legal/compliance rule, a vendor contract, a schema the code must match |
| **Intra-MR coupling** | Only correct because of another change in this same MR (cross-reference it) |
| **Risk concentration** | Migrations, auth checks, money, data deletion, concurrency, cache invalidation |
| **A rejected obvious approach** | The reviewer will ask "why not just X?" - answer it preemptively |

## Skip when any of these holds

| Trigger | Example |
|---|---|
| **Self-describing helper** | 5-10 lines that title-case a string, clamp a number, format a date |
| **Named constant with an obvious value** | `DEBOUNCE_MS = 300`, `MAX_RETRIES = 3`, `PAGE_SIZE = 20` |
| **Pure rename or move** | Covered by one line in the overview, never per-site |
| **Formatting, lint, import order** | Zero semantic content |
| **Mechanical test updates** | Tests that changed only to follow a signature change |
| **Idiomatic boilerplate** | A standard null check, a conventional DTO, a routine getter |
| **Generated or vendored files** | Lockfiles, snapshots, codegen output, migrations written by a tool |
| **Already documented in code** | The docstring the MR adds says it; do not repeat it in the MR |

## Size is not the test

Inferential distance is. The same 6-line function can need an annotation or not:

```js
// SKIP - the name and body say everything
function titleCase(s) {
  return s.split(' ').map(w => w[0].toUpperCase() + w.slice(1)).join(' ');
}
```

```js
// ANNOTATE - 6 lines, but the reviewer cannot tell whether it is correct
// without knowing which encoding contract it implements
function packHeader(flags, len) {
  return ((flags & 0x0f) << 12) | (len & 0x0fff);
}
```

And conversely, a 300-line generated client needs one line in the overview, not 300 inline comments.

## Borderline cases

- **Two annotations would say the same thing.** Write one, in the overview, and mention both files. Repetition reads as noise and trains the reviewer to skim.
- **The whole file is new and non-trivial.** One annotation at the top of the file, about the file's role, beats one per method. Per-method notes on a new file are the single most common way this skill becomes spam.
- **A hunk is non-obvious *only* because the MR is large.** That is a reading-order problem; fix it in the overview's reading order, not with an inline comment.
- **You are unsure.** Skip the inline comment and fold the point into the overview. One extra sentence in a comment the reviewer is already reading costs far less than one more comment.
- **The code is wrong.** This skill is not a review. Tell the user directly, in conversation, and fix it - do not post a comment explaining a defect as though it were intent.

## Budget pressure

Defaults: 1 inline comment per file, 8 per MR.

When more candidates survive the test than the budget allows, keep the ones where being wrong is most expensive - risk concentration (money, auth, data loss, migrations, concurrency) outranks mere novelty. Move the rest into the overview, and tell the user which places lost out, so they can raise the budget if they disagree.

If a single MR legitimately produces far more than 8, the honest finding is that the MR is too large to review well. Say that.
