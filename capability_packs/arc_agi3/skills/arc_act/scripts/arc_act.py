import json

from arc_agi3_runtime import step_arc_session


def arc_act(action: str, prediction: str, reasoning: str, session_id: str = "", x: int = None, y: int = None):
    return json.dumps(
        step_arc_session(session_id, action, x=x, y=y, prediction=prediction, reasoning=reasoning),
        ensure_ascii=False,
    )
