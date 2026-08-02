"""Compatibility alias for layer-neutral detailed tracing."""
from __future__ import annotations

import sys

from app.observability import detailed_trace as _implementation

sys.modules[__name__] = _implementation
