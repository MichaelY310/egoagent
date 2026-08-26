def ask_human(question: str, context: str = ""):
    return {
        "status": "human_required",
        "requires_human": True,
        "question": str(question),
        "context": str(context),
    }
