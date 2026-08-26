def terminate(status: str, summary: str = ""):
    normalized = str(status).lower()
    if normalized not in {"success", "failure"}:
        raise ValueError("status must be success or failure")
    return {
        "terminated": True,
        "status": normalized,
        "summary": str(summary),
    }
