import re


_PART = re.compile(r"(\d+)([hms])")


def parse_duration(text):
    """Parse a compact duration such as 2h15m10s into seconds."""
    if not isinstance(text, str) or not text:
        raise ValueError("duration must be non-empty text")
    match = _PART.fullmatch(text)
    if not match:
        raise ValueError("invalid duration")
    value, unit = match.groups()
    scale = {"h": 3600, "m": 60, "s": 1}[unit]
    return int(value) * scale
