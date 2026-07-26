"""Early, transactional source guards for code-agent workspace edits."""

from __future__ import annotations

import json

from app.agents import validation
from app.agents.repair_session import RepairSession


def _project(*, extra: list[dict] | None = None) -> list[dict]:
    files = [
        {"path": "package.json", "content": '{"scripts":{"build":"vite build"}}'},
        {"path": "index.html", "content": '<script type="module" src="/src/main.ts"></script>'},
        {"path": "src/main.ts", "content": "export const booted = true;"},
        {
            "path": "src/ui/Hud.ts",
            "content": "export class Hud {\n  value = 0;\n}\n",
        },
    ]
    return files + list(extra or [])


def _validation_payload(output: str) -> dict:
    assert output.startswith("error:"), output
    marker = "; validation="
    assert marker in output, output
    return json.loads(output.split(marker, 1)[1])


def test_write_file_rejects_forbidden_api_before_mutation_with_location():
    session = RepairSession.from_files(_project())
    session.checks_ok = True
    before_contents = dict(session.contents)
    before_order = list(session.order)

    output = session.write_file(
        "src/input/Controls.ts",
        "export const controls = {};\nconst saved = localStorage.getItem('keys');\n",
    )

    payload = _validation_payload(output)
    issue = payload["diagnostics"][0]
    assert issue == {
        "code": "forbidden_api",
        "path": "src/input/Controls.ts",
        "line": 2,
        "column": 15,
        "rule": "localStorage",
        "message": "forbidden API in src/input/Controls.ts: localStorage",
    }
    assert session.contents == before_contents
    assert session.order == before_order
    assert session.changed == set()
    assert session.last_patch_delta is None
    assert session.patch_deltas == []
    assert session.checks_ok is True


def test_write_file_rejects_incomplete_typescript_and_reports_opening_line():
    session = RepairSession.from_files(_project())

    output = session.write_file(
        "src/systems/Broken.ts",
        "export function broken(): void {\n  console.log('broken');\n",
    )

    issue = _validation_payload(output)["diagnostics"][0]
    assert issue["code"] == "incomplete_source"
    assert issue["path"] == "src/systems/Broken.ts"
    assert issue["line"] == 1
    assert issue["rule"] == "delimiter_balance"
    assert "src/systems/Broken.ts" not in session.contents


def test_apply_patch_rejects_forbidden_api_without_committing_delta():
    session = RepairSession.from_files(_project())
    original = session.contents["src/ui/Hud.ts"]

    output = session.apply_patch_operation(
        "update_file",
        path="src/ui/Hud.ts",
        diff="-  value = 0;\n+  value = localStorage.length;",
    )

    issue = _validation_payload(output)["diagnostics"][0]
    assert issue["code"] == "forbidden_api"
    assert issue["path"] == "src/ui/Hud.ts"
    assert issue["line"] == 2
    assert session.contents["src/ui/Hud.ts"] == original
    assert session.changed == set()
    assert session.last_patch_delta is None
    assert session.patch_deltas == []


def test_apply_patch_set_rolls_back_every_file_when_one_source_is_unsafe():
    session = RepairSession.from_files(_project())
    original = dict(session.contents)

    output = session.apply_patch_operations(
        [
            {
                "operation_type": "update_file",
                "path": "src/ui/Hud.ts",
                "diff": "-  value = 0;\n+  value = 1;",
            },
            {
                "operation_type": "create_file",
                "path": "src/input/Unsafe.ts",
                "diff": "+export const saved = localStorage.getItem('keys');",
            },
        ]
    )

    issue = _validation_payload(output)["diagnostics"][0]
    assert issue["path"] == "src/input/Unsafe.ts"
    assert issue["code"] == "forbidden_api"
    assert issue["operation"] == 2
    assert session.contents == original
    assert session.changed == set()
    assert session.patch_deltas == []


def test_repair_may_reduce_preexisting_forbidden_findings_incrementally():
    legacy = (
        "export const first = localStorage.getItem('first');\n"
        "export const second = localStorage.getItem('second');\n"
    )
    session = RepairSession.from_files(
        _project(extra=[{"path": "src/input/Legacy.ts", "content": legacy}])
    )

    output = session.apply_patch_operation(
        "update_file",
        path="src/input/Legacy.ts",
        diff="-export const first = localStorage.getItem('first');\n+export const first = null;",
    )

    assert output.startswith("patched "), output
    assert "localStorage.getItem('second')" in session.contents["src/input/Legacy.ts"]
    assert session.changed == {"src/input/Legacy.ts"}
    assert len(session.patch_deltas) == 1


def test_validation_failures_are_structured_and_success_protocol_is_capability_safe():
    session = RepairSession.from_files(_project())

    invalid_path = _validation_payload(
        session.write_file("../escape.ts", "export const escaped = true;")
    )
    assert invalid_path["diagnostics"][0]["code"] == "invalid_path"

    invalid_patch_path = _validation_payload(
        session.apply_patch_operation(
            "create_file",
            path="../escape.ts",
            diff="+export const escaped = true;",
        )
    )
    assert invalid_patch_path["diagnostics"][0]["code"] == "invalid_path"
    assert invalid_patch_path["diagnostics"][0]["path"] == "../escape.ts"

    oversized = _validation_payload(
        session.write_file("src/TooLarge.ts", "x" * (validation.MAX_FILE_BYTES + 1))
    )
    assert oversized["diagnostics"][0]["code"] == "file_too_large"

    written = session.write_file("src/systems/Safe.ts", "export const safe = true;")
    assert "Then run_checks" not in written
    assert "only if that tool is available" in written

    patched = session.apply_patch_operation(
        "update_file",
        path="src/systems/Safe.ts",
        diff="-export const safe = true;\n+export const safe = false;",
    )
    assert "Now call run_checks" not in patched
    assert "only if that tool is available" in patched
