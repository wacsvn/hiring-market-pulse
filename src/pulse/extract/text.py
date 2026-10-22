from __future__ import annotations

import html
import re

_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<\s*(p|br)\s*/?>", re.IGNORECASE)


def html_to_text(raw: str) -> str:
    """HN comment HTML -> plain text, keeping paragraph breaks as newlines."""
    text = _BREAK.sub("\n", raw)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def header_line(text: str) -> str:
    """First line of a post. By thread convention: 'Company | Role | Location | REMOTE | $'."""
    return text.split("\n", 1)[0]
