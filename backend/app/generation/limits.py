"""Retry limits shared by workflow state and task services."""

MAX_REPAIR = 2
MAX_REPLAN = 1
MAX_GAMEPLAY_REPAIR = 2

__all__ = ["MAX_GAMEPLAY_REPAIR", "MAX_REPAIR", "MAX_REPLAN"]
