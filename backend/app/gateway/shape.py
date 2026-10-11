"""What a model call looked like, without keeping the conversation.

Sizes and per-message hashes are always recorded so repeated context can be measured.
Short previews are recorded only when trace content is enabled, and are redacted first.
"""
import hashlib
import json
import re

MAX_MESSAGES = 200
PREVIEW = 500
SECRET = re.compile(r"(?:sk-[A-Za-z0-9_-]{12,}|gw_[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}|AKIA[0-9A-Z]{16}"
                    r"|nlw?_[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._~+/=-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
                    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})")


def redact(text, limit=PREVIEW):
    """Mask credential-shaped strings. This is pattern matching, not a guarantee."""
    text = SECRET.sub("[redacted]", text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str))
    return text if len(text) <= limit else text[:limit] + "…"


def message_text(message):
    content = message.get("content")
    if isinstance(content, list):
        content = " ".join(part if isinstance(part, str) else str(part.get("text", "")) if isinstance(part, dict) else ""
                           for part in content)
    text = content if isinstance(content, str) else ""
    if message.get("tool_calls"):
        text += json.dumps(message["tool_calls"], ensure_ascii=False, default=str)
    return text


def request_shape(body, previews):
    messages = [m for m in body.get("messages", []) if isinstance(m, dict)]
    texts = [message_text(m) for m in messages]
    by_role = {}
    for message, text in zip(messages, texts):
        role = str(message.get("role", "unknown"))[:20]
        by_role[role] = by_role.get(role, 0) + len(text)
    tools = body.get("tools") if isinstance(body.get("tools"), list) else []
    shape = {"messages": len(messages), "prompt_chars": sum(len(t) for t in texts), "chars_by_role": by_role,
             "message_chars": [len(t) for t in texts[:MAX_MESSAGES]],
             "message_hashes": [hashlib.sha256((str(m.get("role")) + "\0" + t).encode()).hexdigest()[:12]
                                for m, t in zip(messages[:MAX_MESSAGES], texts)],
             "tools": len(tools), "tool_schema_chars": len(json.dumps(tools, default=str)) if tools else 0,
             "max_tokens": body.get("max_completion_tokens", body.get("max_tokens"))}
    if previews and messages:
        shape["last_message"] = {"role": str(messages[-1].get("role", "unknown"))[:20], "preview": redact(texts[-1])}
    return shape


def response_shape(payload, previews):
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return {}
    message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
    content = message.get("content") if isinstance(message.get("content"), str) else ""
    calls = [call for call in message.get("tool_calls") or [] if isinstance(call, dict)]
    names = [str((call.get("function") or {}).get("name", ""))[:80] for call in calls[:20]]
    shape = {"finish_reason": str(choices[0].get("finish_reason"))[:40], "output_chars": len(content), "tool_calls": names}
    if previews:
        arguments = [str((call.get("function") or {}).get("arguments", "")) for call in calls[:20]]
        shape["preview"] = redact(content or " ".join(f"{n}({a})" for n, a in zip(names, arguments)))
    return shape


def repeated_prefix(previous, current):
    """How much of this request's opening messages were already sent in the previous call."""
    count = chars = 0
    for old, new, size in zip(previous.get("message_hashes", []), current.get("message_hashes", []),
                              current.get("message_chars", [])):
        if old != new:
            break
        count, chars = count + 1, chars + size
    return count, chars
