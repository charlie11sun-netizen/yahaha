"""Compatibility alias for the layer-neutral LLM runtime."""
from __future__ import annotations

import sys

from app.llm import runtime as _implementation

sys.modules[__name__] = _implementation
