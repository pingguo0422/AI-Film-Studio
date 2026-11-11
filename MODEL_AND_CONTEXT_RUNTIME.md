# Model, semantic review and context runtime — 1.5 dev.2

## Model adapters

`ModelAdapterRegistry` requires an explicit `(provider_key, model_key)` registration. `FakeModelAdapter` is deterministic and labels responses `test_fake`. `OpenAICompatibleAdapter` implements the Chat Completions-compatible JSON-object path and reads credentials from `AFS_MODEL_API_KEY`; its base URL is configurable through `AFS_MODEL_BASE_URL`. No key is committed to the repository. A live request occurs only when application code explicitly invokes `generate()` with credentials configured.

Normalized failures: missing/rejected credentials -> `ModelAuthenticationError`; rate limiting -> `ModelRateLimitError`; timeout/network/provider failures -> `ModelUnavailableError`; malformed envelope/content -> `ModelOutputError`. Provider SDKs are not required.

## Semantic evaluation

`evaluate_with_model()` asks the selected adapter for a strict rubric, validates its shape/ranges, then persists the result through the existing independent-review/evaluation path. Reviewer identity must remain independent of the author Agent. A valid model response is not an approval: evaluation decisions are `accepted`, `rework`, or `escalate`; human governance approval remains separate.

## Context service

`ContextAssembler` accepts explicit immutable `ContextDocument` records. It filters by exact project, task type and allowed sensitivity; records source type, source ID and version ID; enforces per-document character and aggregate estimated-token budgets. The estimate is conservative bookkeeping (`ceil(serialized_chars/4)`), not a provider tokenizer. The service does not silently truncate documents or search arbitrary project data.

## Rework orchestration

A rework task retains the source task/run/evaluation/output and required changes. The service computes the transitive downstream task impact. Queued/retry-wait downstream tasks receive a dependency on the rework task, preventing stale work from starting before the correction completes. Running or terminal downstream tasks are not silently mutated; they are recorded in `downstream_impact` for explicit human replanning. All operations remain in the caller's database transaction; callers must commit or roll back as one unit.

## 《天堂号》8.1 test-mode coverage

The test suite exercises a fake semantic reviewer against an explicit 1909 China-coast-to-Pacific-to-San-Francisco context, persists a review result, and materializes a rework task. The test is deterministic and labelled `test_fake`; it does not claim historical facts have been independently verified or that a live model was called.
