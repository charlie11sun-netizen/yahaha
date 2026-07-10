"""Pure domain rules shared by memory application and profile services."""

import re

from app.models.memory import MemoryCategory

_SECRET_PATTERN = re.compile(
    r"(api[_-]?key|secret|token|password|bearer\s+[a-z0-9._-]{10,}|sk-[a-z0-9_-]{10,})",
    re.IGNORECASE,
)


def category_for_text(text: str) -> str:
    low = text.lower()
    if any(
        keyword in low
        for keyword in (
            "style",
            "visual",
            "pixel",
            "像素",
            "画风",
            "美术",
            "视觉",
            "cozy",
            "写实",
        )
    ):
        return MemoryCategory.STYLE
    if any(
        keyword in low
        for keyword in ("jump", "move", "control", "键", "操作", "手感", "跳跃", "移动")
    ):
        return MemoryCategory.CONTROLS
    if any(
        keyword in low
        for keyword in ("hard", "easy", "difficulty", "难", "简单", "太快", "太慢", "节奏")
    ):
        return MemoryCategory.DIFFICULTY
    if any(
        keyword in low
        for keyword in ("keep", "preserve", "don't change", "不要改", "保留", "不能变")
    ):
        return MemoryCategory.CONSTRAINTS
    if any(
        keyword in low
        for keyword in ("enemy", "boss", "powerup", "mechanic", "敌人", "机制", "道具")
    ):
        return MemoryCategory.MECHANICS
    return MemoryCategory.FEEDBACK


def should_skip_memory_candidate(text: str) -> bool:
    return len(text.strip()) < 8 or bool(_SECRET_PATTERN.search(text))


__all__ = ["category_for_text", "should_skip_memory_candidate"]
