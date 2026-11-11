# Footage-Mode integration boundary

This adapter is a new AFS-side integration layer. It does not rewrite the Footage-Mode package.

## Implemented

- ZIP integrity, version metadata and SHA-256 inspection.
- Safe extraction into a caller-provided empty workspace; rejects path traversal, symlinks, non-empty workspaces, oversized archives and duplicate destination writes.
- Explicit script execution by argument array with `shell=False`, bounded timeout and isolated working directory.
- Source validation with strict integer line ranges (Python booleans are rejected).
- Event, performance-track and coverage-decision canonical mapping helpers.
- Preservation of source line ranges, event source keys, parallel track links and timing provenance.
- Coverage decision semantic checks for `covered`, `partially_covered`, and `not_selected`.
- Export refuses to overwrite an existing destination.
- QC output is mapped as technical QC and never promoted to human approval.

## Provenance rule

The 2.2-B Heaven Ship 8.1 pressure-test file explicitly reports `scene.source_type = acting_task`. Its 52 event decisions are therefore mapped as `SOURCE_ACTING_TASK`, not `SOURCE_SCREENPLAY`. The adapter preserves `selected_shot_ids` as source keys; it does not invent canonical AFS shot/entity IDs. These keys must be resolved through `integration_object_mappings` before any canonical entity links are written.

## Execution example

```python
from integrations.footage_mode.adapter import FootageModeAdapter

adapter = FootageModeAdapter()
package = adapter.inspect_source("source-baseline/Footage-Mode-2.2-B.zip")
result = adapter.execute_script(
    "source-baseline/Footage-Mode-2.2-B.zip",
    "/tmp/afs-fm-isolated-run-001",  # must be empty or not yet exist
    "2.2-dev-recovered/scripts/footage_mode.py",
    args=["selftest"],
    timeout_seconds=120,
)
assert result.exit_code == 0
```

The caller owns the isolated workspace lifecycle and must archive required outputs before deleting it. The adapter does not mutate the original ZIP or source tree.

## Not yet implemented

- Full scene/shot/character/Visual Bible schema conversion.
- Rerunning the Footage-Mode optimizer as a managed Skill execution job; the current 8.1 Skill imports and validates the package's existing optimizer outputs.
- AFS approval workflow integration for coverage proposals.
- Production isolation/container sandboxing for executing third-party code.

## AFS database persistence (1.2 development slice)

The `persistence.py` service imports the real Heaven Ship 8.1 event and coverage
JSON documents as one atomic AFS integration run. It stores 52 original event
snapshots, 52 original coverage-decision snapshots, 52 source ranges and 52
proposed coverage decisions. Source provenance remains `SOURCE_ACTING_TASK`.

No character, event or shot UUID is guessed. `selected_shot_source_keys` are
preserved as Footage-Mode keys; `selected_shot_entity_ids` remains empty until
an explicit `integration_object_mappings` row resolves each key. Imported
coverage always remains `review_state=proposed` and requires human review.

With an existing AFS project and a configured `AFS_DATABASE_URL`:

```bash
python scripts/import_footage_mode_81.py \
  --archive source-baseline/Footage-Mode-2.2-B.zip \
  --project-id <existing-project-uuid> \
  --idempotency-key heaven-ship-S08-import-01 \
  --export /path/to/heaven-ship-S08-export.json
```

The CLI uses the configured database connection; it does not create a project or
silently apply migrations. The export path is create-only and will not overwrite
an existing file. A fresh SQLAlchemy Session is required for each import call.

## Explicit canonical mapping (Foundation 1.2 dev.2)

Use `mapping_service.register_source_mapping(...)` only after an explicit source
key ↔ existing AFS UUID decision has been reviewed. Supported source object types
are `dramatic_event`, `shot`, and `character`; target entity types must match and
belong to the same project as the integration source. A rationale is mandatory.
The service rejects remapping an already mapped key to a different entity.

After all event and selected-shot keys have explicit mappings, call
`resolve_run_coverage_links(...)`. It fails closed if any required key is missing.
It does not mutate the immutable `FMCoverageDecision` proposal; canonical links
are maintained in the mapping registry and included in `export_run_bundle()` as
`canonical_links`. This operation is not an approval.


## Agent Runtime Skill (Foundation 1.3 dev.1)

`skill.py` exposes `build_heaven_ship_81_validation_executor(...)` as a provider-neutral registered Skill executor. The runtime pins exact AgentVersion and SkillVersion IDs, requires an explicit `AgentSkillBinding`, creates AgentRun/SkillRun records and persists the integration result.

For an end-to-end CLI run, see `scripts/run_footage_mode_81_agent.py` in the AFS workspace. It registers the AI Executive Director and Footage-Mode validation Skill idempotently, creates an idempotent project task, and runs the adapter. The current operation validates/imports existing 8.1 outputs; it does not rerun the optimizer, call an LLM, create canonical entity IDs, or approve proposals.
