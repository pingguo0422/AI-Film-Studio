import json
import zipfile
import pytest
from pathlib import Path
from integrations.footage_mode.adapter import FootageModeAdapter, FootageModeAdapterError
from integrations.footage_mode.qc_mapper import qc_to_canonical

ROOT = Path(__file__).resolve().parents[1]
FM_ARCHIVE = ROOT / "source-baseline" / "Footage-Mode-2.2-B.zip"

def test_inspect_preserved_footage_mode_package():
    descriptor = FootageModeAdapter().inspect_source(FM_ARCHIVE)
    assert descriptor.name == "Footage-Mode"
    assert descriptor.version == "2.2.0-recovered-b.1"
    assert descriptor.release_status == "provisional_reconstruction"
    assert len(descriptor.archive_sha256) == 64

def test_event_validation_preserves_source_and_rejects_bool_line_number():
    adapter = FootageModeAdapter()
    event = {"event_id":"E1", "event_types":["action"], "source":{"line_start":12,"line_end":14,"exact_text":"动作"}}
    mapped = adapter.validate_event(event, "SOURCE_ACTING_TASK")
    assert mapped["source"] == event["source"]
    assert mapped["source_kind"] == "SOURCE_ACTING_TASK"
    with pytest.raises(FootageModeAdapterError):
        adapter.validate_event({"event_types":"action"}, "SOURCE_ACTING_TASK")
    with pytest.raises(FootageModeAdapterError):
        adapter.validate_event({"event_types":[],"source":{"line_start":True,"line_end":2}}, "SOURCE_SCREENPLAY")

def test_coverage_semantics_are_preserved_and_never_auto_approved():
    adapter=FootageModeAdapter()
    decision={"status":"partially_covered","required_dimensions":["action","reaction"],"covered_dimensions":["action"]}
    mapped=adapter.validate_coverage_decision(decision)
    assert mapped["coverage_status"] == "partially_covered"
    assert mapped["review_state"] == "proposed"
    assert mapped["human_review_required"] is True
    with pytest.raises(FootageModeAdapterError):
        adapter.validate_coverage_decision({"status":"covered","required_dimensions":["action","reaction"],"covered_dimensions":["action"]})

def test_parallel_track_relationships_are_not_flattened():
    track={"track_key":"武寒青","track_kind":"character","parallel_with":["厨师","猪仔群"],"timing_provenance":{"source":"estimated"}}
    mapped=FootageModeAdapter().validate_track(track)
    assert mapped["parallel_with"] == ["厨师","猪仔群"]
    assert mapped["timing_provenance"]["source"] == "estimated"

def test_extract_isolated_and_execute_without_shell(tmp_path):
    package=tmp_path/"fixture.zip"
    with zipfile.ZipFile(package,"w") as z:
        z.writestr("pkg/VERSION-2.2.json",json.dumps({"name":"Footage-Mode","version":"test-1","release_status":"test"}))
        z.writestr("pkg/scripts/echo.py","print('isolated-ok')\n")
    workspace=tmp_path/"isolated"
    result=FootageModeAdapter().execute_script(package,workspace,"pkg/scripts/echo.py",args=[])
    assert result.exit_code == 0
    assert result.stdout.strip() == "isolated-ok"
    assert Path(result.workspace,"pkg/scripts/echo.py").is_file()

def test_export_refuses_to_overwrite(tmp_path):
    path=tmp_path/"export.json"
    adapter=FootageModeAdapter()
    adapter.export_json({"ok":True},path)
    with pytest.raises(FootageModeAdapterError):
        adapter.export_json({"ok":False},path)

def test_qc_is_not_promoted_to_human_approval():
    mapped=qc_to_canonical({"status":"pass","warnings":[]})
    assert mapped["status"] == "pass"
    assert mapped["human_approval"] is False
    assert mapped["review_state"] == "proposed"

def test_real_heaven_ship_coverage_contract_maps_all_52_events_with_correct_provenance():
    from integrations.footage_mode.schema_mapper import coverage_to_canonical, source_kind_from_scene
    with zipfile.ZipFile(FM_ARCHIVE) as archive:
        name=next(n for n in archive.namelist() if n.endswith("heaven-ship-8.1-coverage-decisions.json"))
        document=json.loads(archive.read(name))
    source_kind=source_kind_from_scene(document["scene"])
    assert source_kind == "SOURCE_ACTING_TASK"
    mapped=[coverage_to_canonical(item, source_kind) for item in document["event_decisions"]]
    assert len(mapped) == 52
    assert mapped[0]["event_source_key"] == "S08-001"
    assert mapped[0]["source_range_snapshot"] == {"source_kind":"SOURCE_ACTING_TASK", "source_line_range":[11,11]}
    assert mapped[0]["review_state"] == "proposed"
    assert all(item["human_review_required"] for item in mapped)
    assert all(item["selected_shot_entity_ids"] == [] for item in mapped)

def test_adapter_does_not_guess_missing_source_provenance():
    from integrations.footage_mode.schema_mapper import source_kind_from_scene
    with pytest.raises(ValueError):
        source_kind_from_scene({"scene_id":"S08"})

def test_adapter_rejects_malformed_dimension_and_parallel_arrays():
    adapter=FootageModeAdapter()
    with pytest.raises(FootageModeAdapterError):
        adapter.validate_coverage_decision({"status":"covered","required_dimensions":[{}],"covered_dimensions":[]})
    with pytest.raises(FootageModeAdapterError):
        adapter.validate_track({"parallel_with":"CHARACTER_B"})

def test_screenplay_and_acting_task_are_explicit_text_sources():
    adapter=FootageModeAdapter()
    assert adapter.validate_input("INT. ROOM - NIGHT", "SOURCE_SCREENPLAY").startswith("INT.")
    assert adapter.validate_input("ACTING TASK: ...", "SOURCE_ACTING_TASK").startswith("ACTING")
    with pytest.raises(FootageModeAdapterError):
        adapter.validate_event({"event_types":[]}, "UNKNOWN_SOURCE")
