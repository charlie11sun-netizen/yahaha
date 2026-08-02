"""Compatibility alias for the layer-neutral Opik integration."""
from __future__ import annotations

import sys

from app.observability import opik_integration as _implementation

sys.modules[__name__] = _implementation
