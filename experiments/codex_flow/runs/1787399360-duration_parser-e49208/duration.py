import re


_PART = re.compile(r"(\d+)([hms])")
_ORDER = {"h": 0, "m": 1, "s": 2}


def parse_duration(text):
    """Parse a compact duration such as 2h15m10s into seconds."""
    if not isinstance(text, str) or not text:
        raise ValueError("duration must be non-empty text")
    parts = list(_PART.finditer(text))
    if not parts or "".join(m.group() for m in parts) != text:
        raise ValueError("invalid duration")
    total = 0
    last_order = -1
    for match in parts:
        value, unit = match.groups()
        order = _ORDER[unit]
        if order <= last_order:
            raise ValueError("invalid duration")
        last_order = order
        scale = {"h": 3600, "m": 60, "s": 1}[unit]
        total += int(value) * scale
    return total
