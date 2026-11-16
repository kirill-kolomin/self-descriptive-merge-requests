# Annotation format

Two comment shapes: one **overview** comment per MR, and a small number of **inline** comments. Both are built from the same three sections, at different scales.

Rules that apply to both:

- **Plain language.** Write for a competent engineer who has never seen this code. No jargon the codebase does not already use, no restating the diff in prose ("this adds a function named `x`" is worthless - the reviewer can see that).
- **Say the thing, not that there is a thing.** "Retries are now capped at 3" beats "retry behavior was adjusted".
- **Omit a section rather than padding it.** A section with nothing real to say costs the reviewer a read and teaches them to skim the next one.
- **No review verdicts.** This skill explains; it does not approve, praise, or critique. "This is a clean approach" is noise.
- **Every comment ends with its marker line** (see SKILL.md §7).

## Overview comment

Posted as an MR-level comment (not inline). This is the reviewer's entry point.

```markdown
## What this MR does

<2-3 sentences of intent, in plain language: the problem and the chosen approach.
Why this approach, if an obvious alternative was rejected.>

## Behavior: before → after

| | Before | After |
|---|---|---|
| <observable aspect> | <what happened> | <what happens now> |
| <observable aspect> | <what happened> | <what happens now> |

<Any behavior that is NOT changing but looks like it should be - this is where
reviewers most often misread a diff.>

## Entry points

How the changed code is reached, per area (max 3 levels deep):

- `POST /api/orders` → `OrderController.create` → **`PricingService.quote`** (changed)
- `cli: sync --full` → `SyncRunner.run` → **`PricingService.quote`** (changed)
- `src/utils/retry.ts` → entry point unresolved (registered through the DI container by string key)

## Reading order

1. `src/pricing/service.ts` - the actual change, start here
2. `src/pricing/types.ts` - types the above needs
3. `src/**/__tests__/*` - mechanical follow-through, skim

## Inline notes

- [`service.ts` - rounding order](<url>)
- [`retry.ts` - why the backoff is not exponential](<url>)

<!-- sdmr:v1 kind=overview -->
```

Section notes:

- **Behavior table** - use it when there are two or more observable changes; a single change is clearer as one sentence. For a brand-new component, write "new - no prior behavior" rather than inventing a before-state.
- **Entry points** - one line per changed area, not per function. Bold the changed node. Mark unresolved chains explicitly; never guess (SKILL.md §4).
- **Reading order** - the highest-value section for a large MR and the easiest to get wrong: it must reflect dependency, not file order.
- **Inline notes** - filled in during phase 2 of cross-referencing. If there are no inline comments, drop the section.

## Inline comment

Anchored to a specific new-side line inside a hunk. Shorter than the overview - it is read inside a cramped diff view.

```markdown
**Why:** <1-2 sentences. The question the reviewer would have asked.>

**Before → after:** <one line, or omit if this hunk changes no behavior>

**Reached from:** <entry point chain, or omit if the same as the overview's>

<!-- sdmr:v1 kind=inline slug=rounding-order anchor=src/pricing/service.ts@84 fp=a1b2c3d4 -->
```

Three to six lines total. If an inline comment needs more than that, the explanation is about the MR as a whole - move it to the overview and link to the line from there.

### Worked example - annotate

```diff
+  const total = round(subtotal * (1 + taxRate), 2);
-  const total = round(subtotal, 2) * (1 + taxRate);
```

```markdown
**Why:** Tax must be applied before rounding, otherwise each line item rounds twice and
invoices drift by up to a cent per item - the bug in #4412.

**Before → after:** Totals change by at most 1 cent on multi-item invoices; the stored
rounding mode is unchanged, so historical invoices are not affected.

**Reached from:** `POST /api/orders` → `OrderController.create` → `PricingService.quote`

<!-- sdmr:v1 kind=inline slug=rounding-order anchor=src/pricing/service.ts@84 fp=a1b2c3d4 -->
```

### Worked example - skip

```diff
+const DEBOUNCE_MS = 300;
```

No comment. The name states the unit and the purpose; 300ms is an unremarkable value. Annotating it would spend reviewer attention to tell them what they already read.

## Cross-reference tokens

While drafting, write cross-links as `[[ref:<slug>]]`:

```markdown
**Why:** The cache key now includes the tenant id because `TenantResolver` started
returning per-tenant configs in this same MR - see [[ref:tenant-resolver]].
```

Slugs are stable, lowercase, hyphenated, and unique per MR. After posting, replace every token with a real link to the posted comment (SKILL.md §6, phase 2). A `[[ref:...]]` token left in a posted comment is a visible defect - grep the final bodies for `[[ref:` before declaring done.
