"""Compatibility alias for the layer-neutral LLM provider."""
from __future__ import annotations

import sys

from app.llm import provider as _implementation

sys.modules[__name__] = _implementation
