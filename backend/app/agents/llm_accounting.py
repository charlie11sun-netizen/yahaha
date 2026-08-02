"""Compatibility alias for layer-neutral LLM accounting."""
from __future__ import annotations

import sys

from app.llm import accounting as _implementation

sys.modules[__name__] = _implementation
