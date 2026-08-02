"""Compatibility alias for the layer-neutral LLM cache."""
from __future__ import annotations

import sys

from app.llm import cache as _implementation

sys.modules[__name__] = _implementation
