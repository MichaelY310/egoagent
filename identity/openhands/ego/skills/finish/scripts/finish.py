def finish(summary: str = ""):
    """Return a normal observation; the DAG routes this control tool to its judge."""

    return {
        "ok": True,
        "status": "ready_for_review",
        "summary": str(summary or "Work attempt submitted for independent review."),
    }
