from enum import Enum


class AgentStreamRetryRequired(RuntimeError):
    """An agent stage could not run because the model stream/transport failed.

    This is infrastructure failure, not a wrong answer: escalating it to a
    regeneration fallback destroys good work (2026-07-20 三路守卫: a repair-agent
    connection outage cascaded into regenerating already-successful image
    assets on the same broken gateway, killing the task). Raising this pauses
    the task with its checkpoint retained; a manual retry resumes the same node.
    """


class AuthorTeamRetryRequired(RuntimeError):
    """Required author-team owners failed, so integration must wait for retry.

    Integration is allowed to compose accepted owner work, not replace missing
    implementation teams. Keeping this as a distinct pause signal preserves
    the code-generation checkpoint and lets a manual task retry rerun the node.
    """


class TaskErrorCode(str, Enum):
    SAFETY_REJECTED = "SAFETY_REJECTED"
    MODERATION_BLOCKED = "MODERATION_BLOCKED"
    PROMPT_TOO_LONG = "PROMPT_TOO_LONG"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_INVALID_OUTPUT = "MODEL_INVALID_OUTPUT"
    ASSET_GENERATION_FAILED = "ASSET_GENERATION_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    SMOKE_FAILED = "SMOKE_FAILED"
    QA_FAILED = "QA_FAILED"
    SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    RECURSION_LIMIT = "RECURSION_LIMIT"
    PUBLISH_FAILED = "PUBLISH_FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
