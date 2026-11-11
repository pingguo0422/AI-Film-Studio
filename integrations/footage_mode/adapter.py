"""Isolated adapter boundary for Footage-Mode packages.

The adapter never edits the supplied source archive or source workspace. Script
execution is opt-in, uses an extracted temporary workspace, and never invokes a shell.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import zipfile

class FootageModeAdapterError(Exception):
    pass

@dataclass(frozen=True)
class PackageDescriptor:
    name: str
    version: str
    release_status: str | None
    archive_sha256: str
    member_count: int

@dataclass(frozen=True)
class ExecutionResult:
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    workspace: str

class FootageModeAdapter:
    def inspect_source(self, archive_path: str | Path) -> PackageDescriptor:
        path = Path(archive_path)
        if not path.is_file() or not zipfile.is_zipfile(path):
            raise FootageModeAdapterError("source package must be an existing ZIP archive")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            with zipfile.ZipFile(path) as archive:
                if len(archive.infolist()) > 20000 or sum(item.file_size for item in archive.infolist()) > 1_000_000_000:
                    raise FootageModeAdapterError("source archive exceeds configured extraction limits")
                bad_member = archive.testzip()
                if bad_member:
                    raise FootageModeAdapterError(f"corrupt ZIP member: {bad_member}")
                version_files = [n for n in archive.namelist() if n.endswith("VERSION-2.2.json")]
                if not version_files:
                    raise FootageModeAdapterError("Footage-Mode VERSION-2.2.json not found")
                metadata = json.loads(archive.read(version_files[0]).decode("utf-8"))
                return PackageDescriptor(
                    name=str(metadata.get("name", "Footage-Mode")),
                    version=str(metadata.get("version", "unknown")),
                    release_status=metadata.get("release_status"),
                    archive_sha256=digest,
                    member_count=len(archive.namelist()),
                )
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise FootageModeAdapterError(f"cannot inspect source package: {exc}") from exc

    def validate_input(self, payload: Any, source_kind: str) -> dict[str, Any] | str:
        if source_kind in {"SOURCE_ACTING_TASK", "SOURCE_SCREENPLAY"}:
            if not isinstance(payload, str) or not payload.strip():
                raise FootageModeAdapterError("screenplay/ACTING TASK source must be non-empty text")
            return payload
        if not isinstance(payload, dict):
            raise FootageModeAdapterError("structured Footage-Mode input must be a JSON object")
        if source_kind not in {"SOURCE_SCENE_JSON", "SOURCE_EVENTS_JSON", "SOURCE_COVERAGE_JSON", "SOURCE_SHOTS_JSON"}:
            raise FootageModeAdapterError(f"unsupported source kind: {source_kind}")
        return payload

    def validate_event(self, event: dict[str, Any], source_kind: str) -> dict[str, Any]:
        if source_kind not in {"SOURCE_ACTING_TASK", "SOURCE_SCREENPLAY", "SOURCE_SCENE_JSON", "SOURCE_EVENTS_JSON", "SOURCE_SHOTS_JSON"}:
            raise FootageModeAdapterError("event source provenance must be explicit and supported")
        if not isinstance(event, dict):
            raise FootageModeAdapterError("event must be an object")
        source = event.get("source")
        if source is not None:
            if not isinstance(source, dict):
                raise FootageModeAdapterError("event.source must be an object")
            for field in ("line_start", "line_end"):
                value = source.get(field)
                if value is not None and type(value) is not int:
                    raise FootageModeAdapterError(f"source.{field} must be an integer, not bool or another type")
            start, end = source.get("line_start"), source.get("line_end")
            if start is not None and (start <= 0 or end is None or end < start):
                raise FootageModeAdapterError("event source line range is invalid")
            if end is not None and start is None:
                raise FootageModeAdapterError("source.line_end cannot exist without source.line_start")
        event_types = event.get("event_types", [])
        if not isinstance(event_types, list) or any(not isinstance(x, str) for x in event_types):
            raise FootageModeAdapterError("event_types must be a list of strings")
        # Preserve source semantics and provenance without silently renaming or dropping fields.
        canonical = dict(event)
        canonical["source_kind"] = source_kind
        return canonical

    def validate_coverage_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(decision, dict):
            raise FootageModeAdapterError("coverage decision must be an object")
        status = decision.get("status", decision.get("coverage_status"))
        allowed = {"covered", "partially_covered", "not_selected"}
        if status not in allowed:
            raise FootageModeAdapterError("coverage status must be covered, partially_covered, or not_selected")
        required = decision.get("required_dimensions")
        covered = decision.get("covered_dimensions")
        if not isinstance(required, list) or not isinstance(covered, list):
            raise FootageModeAdapterError("required_dimensions and covered_dimensions must be arrays")
        if any(not isinstance(x, str) or not x for x in required + covered):
            raise FootageModeAdapterError("coverage dimensions must be non-empty strings")
        if len(set(required)) != len(required) or len(set(covered)) != len(covered):
            raise FootageModeAdapterError("coverage dimensions must not contain duplicates")
        required_set, covered_set = set(required), set(covered)
        if not covered_set.issubset(required_set):
            raise FootageModeAdapterError("covered dimensions must be a subset of required dimensions")
        if status == "covered" and required_set != covered_set:
            raise FootageModeAdapterError("covered status requires every required dimension")
        if status == "partially_covered" and not (covered_set and covered_set < required_set):
            raise FootageModeAdapterError("partially_covered requires some, but not all, dimensions")
        if status == "not_selected" and covered_set:
            raise FootageModeAdapterError("not_selected cannot claim covered dimensions")
        canonical = dict(decision)
        canonical["coverage_status"] = status
        canonical["review_state"] = "proposed"
        canonical["human_review_required"] = True
        return canonical

    def validate_track(self, track: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(track, dict):
            raise FootageModeAdapterError("performance track must be an object")
        parallel_with = track.get("parallel_with", [])
        if not isinstance(parallel_with, list) or any(not isinstance(x, str) or not x for x in parallel_with):
            raise FootageModeAdapterError("parallel_with must be an array of track keys; parallel tracks must not be flattened")
        provenance = track.get("timing_provenance", {})
        if not isinstance(provenance, dict):
            raise FootageModeAdapterError("timing_provenance must be an object")
        canonical = dict(track)
        canonical["parallel_with"] = list(parallel_with)
        canonical["timing_provenance"] = dict(provenance)
        return canonical

    def extract_isolated(self, archive_path: str | Path, workspace: str | Path) -> Path:
        archive_path, root = Path(archive_path), Path(workspace).resolve()
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise FootageModeAdapterError("isolated workspace must be empty; refusing to overwrite existing files")
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                member = PurePosixPath(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise FootageModeAdapterError("unsafe path in source archive")
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise FootageModeAdapterError("symbolic links are not allowed in source archive")
                destination = (root / Path(*member.parts)).resolve()
                if root not in destination.parents and destination != root:
                    raise FootageModeAdapterError("archive member escapes isolated workspace")
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as src, destination.open("xb") as dst:
                        shutil.copyfileobj(src, dst)
        return root

    def execute_script(
        self,
        archive_path: str | Path,
        workspace: str | Path,
        script_relative_path: str,
        args: list[str] | None = None,
        timeout_seconds: int = 120,
    ) -> ExecutionResult:
        if timeout_seconds < 1 or timeout_seconds > 3600:
            raise FootageModeAdapterError("timeout_seconds must be between 1 and 3600")
        workspace = self.extract_isolated(archive_path, workspace)
        script = (workspace / script_relative_path).resolve()
        if workspace not in script.parents or not script.is_file() or script.suffix != ".py":
            raise FootageModeAdapterError("script must be an existing Python file inside the isolated package")
        if args is not None and (not isinstance(args, list) or any(not isinstance(x, str) for x in args)):
            raise FootageModeAdapterError("args must be a list of strings; shell command strings are not accepted")
        command = [sys.executable, str(script), *(args or [])]
        try:
            completed = subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=timeout_seconds, check=False, shell=False)
        except subprocess.TimeoutExpired as exc:
            raise FootageModeAdapterError("Footage-Mode execution timed out") from exc
        return ExecutionResult(tuple(command), completed.returncode, completed.stdout, completed.stderr, str(workspace))

    def export_json(self, payload: dict[str, Any], destination: str | Path) -> Path:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\\n")
        except FileExistsError as exc:
            raise FootageModeAdapterError("export destination already exists; refusing to overwrite") from exc
        return path
