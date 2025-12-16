from __future__ import annotations

import re

HEADING_RE = re.compile(r"^\s*#{1,6}\s*(.*)$")
BULLET_RE = re.compile(r"^\s*[*-]\s*(.*)$")


def _strip_bold_markers(text: str) -> str:
    """Убирает маркеры жирного шрифта Markdown."""

    return text.replace("**", "").replace("__", "")


def _normalize_line(line: str) -> str:
    stripped = line.rstrip()

    heading_match = HEADING_RE.match(stripped)
    if heading_match:
        stripped = heading_match.group(1)

    bullet_match = BULLET_RE.match(stripped)
    if bullet_match and bullet_match.group(1).strip():
        return f"— {bullet_match.group(1).strip()}"

    return stripped.strip()


def normalize_chat_text(text: str) -> str:
    """Нормализует текст ответа для отображения в UI."""

    if not text:
        return ""

    cleaned = _strip_bold_markers(text)

    normalized_lines: list[str] = []
    previous_blank = False

    for raw_line in cleaned.splitlines():
        normalized_line = _normalize_line(raw_line)

        if not normalized_line:
            if previous_blank:
                continue
            previous_blank = True
            normalized_lines.append("")
            continue

        normalized_lines.append(normalized_line)
        previous_blank = False

    return "\n".join(normalized_lines).strip()


__all__ = ["normalize_chat_text"]
