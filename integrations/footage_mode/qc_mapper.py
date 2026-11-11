"""Map tool QC to AFS QC without converting tool output into human approval."""

def qc_to_canonical(report: dict) -> dict:
    if not isinstance(report, dict):
        raise ValueError("QC report must be an object")
    raw_status = str(report.get("status", "incomplete")).lower()
    mapping = {"pass": "pass", "warning": "warning", "fail": "fail", "incomplete": "incomplete"}
    status = mapping.get(raw_status, "incomplete")
    return {
        "qc_type": "technical",
        "status": status,
        "findings": dict(report),
        "human_approval": False,
        "review_state": "proposed",
    }
