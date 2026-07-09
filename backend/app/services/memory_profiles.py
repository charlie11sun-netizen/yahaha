"""Compatibility facade for memory profile services.

Implementation is split by responsibility across adjacent modules; this module
keeps the historical import path stable for routers, services, and tests.
"""

from __future__ import annotations

from app.services.memory_profile_common import *
from app.services.memory_profile_extraction import *
from app.services.memory_profile_lifecycle import *
from app.services.memory_profile_evidence import *
from app.services.memory_profile_queries import *

__all__ = [name for name in globals() if not name.startswith("__")]
