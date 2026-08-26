import json

from arc_agi3_runtime import arc_session_status


def arc_status(session_id: str = ""):
    return json.dumps(arc_session_status(session_id), ensure_ascii=False)
