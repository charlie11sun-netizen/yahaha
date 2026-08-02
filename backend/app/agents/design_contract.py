"""Compatibility alias for the layer-neutral design contract."""
from __future__ import annotations

import sys

from app.generation import design_contract as _implementation

sys.modules[__name__] = _implementation
