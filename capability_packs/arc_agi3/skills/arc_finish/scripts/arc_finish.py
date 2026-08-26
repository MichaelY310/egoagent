import json

from arc_agi3_runtime import finish_arc_session


def arc_finish(session_id: str = ""):
    return json.dumps(finish_arc_session(session_id), ensure_ascii=False)
