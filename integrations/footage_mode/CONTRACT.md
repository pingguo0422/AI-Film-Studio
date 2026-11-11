# Footage-Mode ↔ AFS adapter contract

## Provenance

- Preserve `SOURCE_ACTING_TASK`, `SOURCE_SCREENPLAY`, `SOURCE_SCENE_JSON`, `SOURCE_EVENTS_JSON`, and `SOURCE_SHOTS_JSON` explicitly.
- Never infer screenplay origin from an ACTING TASK or scene label.
- Preserve `source.line_start`, `source.line_end`, `source.exact_text`, or source line range arrays without normalization that loses source positions.
- Keep raw source snapshots and package version/hash with every integration run.

## Event semantics

Preserve event IDs, event types, actor/character identifiers, clusters, linked event IDs, observable actions, dramatic state, information delta, power relation, visual evidence, priority, confidence, human review requirement, and inference policy. Unknown or unsupported fields remain in raw snapshots.

## Coverage semantics

- `covered`: all required dimensions explicitly covered.
- `partially_covered`: at least one but not all required dimensions covered.
- `not_selected`: no required dimensions covered.
- Unselected candidate shots do not count as coverage.
- Master/context coverage without explicit dimension mapping receives no coverage credit.
- Source shot IDs remain source keys until mapped to canonical AFS entities.
- Every decision starts as a proposal and requires human review.

## Performance tracks and time

- Preserve stable character identity and separate character/group tracks.
- Preserve concurrency groups and `parallel_with`; do not serialize simultaneous tracks.
- Preserve timing provenance (`authored`, `estimated`, `measured`, `unknown`).
- Do not convert estimated time into measured time.
- Keep source time/range separate from clip-local render time/range.

## Execution boundary

The adapter extracts the source ZIP into a new empty isolated workspace, rejects unsafe archive paths/symlinks, executes an explicit Python script by argument list (`shell=False`) with a bounded timeout, and records package hash, command, exit status and output. It never edits the original package. The current isolation is a separate filesystem workspace, not yet a hardened container sandbox.
