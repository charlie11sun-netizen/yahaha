"""Write the FastAPI OpenAPI document for frontend type generation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.main import app


def main() -> int:
    output = sys.argv[1] if len(sys.argv) > 1 else "-"
    document = app.openapi()
    payload = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
    if output == "-":
        sys.stdout.write(payload)
        sys.stdout.write("\n")
        return 0
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
