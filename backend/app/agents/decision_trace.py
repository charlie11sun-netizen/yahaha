"""Compatibility alias for the layer-neutral decision trace helpers."""
from __future__ import annotations

import sys

from app.observability import decision_trace as _implementation

sys.modules[__name__] = _implementation
