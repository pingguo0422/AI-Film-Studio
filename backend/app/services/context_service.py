"""Task-scoped context assembly with provenance and deterministic size limits."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from uuid import UUID

class ContextError(ValueError): pass

@dataclass(frozen=True)
class ContextDocument:
    project_id: UUID
    source_type: str
    source_id: str
    version_id: str
    content: dict[str, Any]
    allowed_task_types: tuple[str, ...] = ()
    sensitivity: str = "project"

@dataclass(frozen=True)
class ContextBundle:
    project_id: str
    task_type: str
    documents: tuple[dict[str, Any], ...]
    provenance: tuple[dict[str, str], ...]
    estimated_tokens: int

class ContextAssembler:
    def __init__(self, *, max_tokens: int = 6000, max_document_chars: int = 24000):
        if max_tokens < 1 or max_document_chars < 1: raise ValueError("context limits must be positive")
        self.max_tokens, self.max_document_chars = max_tokens, max_document_chars
    def assemble(self, *, project_id: UUID, task_type: str, documents: list[ContextDocument],
                 allowed_sensitivity: tuple[str, ...] = ("project", "public")) -> ContextBundle:
        if not task_type.strip(): raise ContextError("task_type is required")
        selected, provenance, used = [], [], 0
        for doc in documents:
            if doc.project_id != project_id: continue
            if doc.sensitivity not in allowed_sensitivity: continue
            if doc.allowed_task_types and task_type not in doc.allowed_task_types: continue
            if not isinstance(doc.content, dict): raise ContextError("context document content must be an object")
            import json
            serialized = json.dumps(doc.content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if len(serialized) > self.max_document_chars: raise ContextError(f"context document exceeds per-document limit: {doc.source_id}")
            estimate = max(1, (len(serialized) + 3) // 4)
            if used + estimate > self.max_tokens: raise ContextError("assembled context exceeds token budget; narrow task scope")
            used += estimate; selected.append(dict(doc.content))
            provenance.append({"source_type": doc.source_type, "source_id": doc.source_id, "version_id": doc.version_id})
        return ContextBundle(str(project_id), task_type, tuple(selected), tuple(provenance), used)
