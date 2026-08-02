"""Apply LangGraph checkpoint schema migrations."""

from app.core.checkpointing import setup_checkpointer


def main() -> int:
    setup_checkpointer()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
