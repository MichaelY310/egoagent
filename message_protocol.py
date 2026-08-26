"""Provider-neutral model message normalization."""

from __future__ import annotations

import copy
import json


def compose_model_messages(system_prompt, messages):
    """Build one provider-safe system prefix followed by non-system history.

    Context components can contribute system-role summaries. Providers and
    training tokenizers disagree about repeated system messages, so the final
    adapter request merges them while preserving section labels and content.
    The trajectory stores this exact merged request.
    """

    sections = []
    if system_prompt:
        sections.append(str(system_prompt))
    body = []
    for message in messages or []:
        if message.get("role") != "system":
            body.append(copy.deepcopy(message))
            continue
        content = message.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, separators=(",", ":"), default=str)
        name = str(message.get("name") or "").strip()
        sections.append(f"[{name}]\n{content}" if name else content)
    if not sections:
        return body
    return [{"role": "system", "content": "\n\n".join(section for section in sections if section)}] + body
