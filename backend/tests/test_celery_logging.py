import json
import os
import subprocess
import sys
from pathlib import Path


def test_bind_context_none_unbinds_structlog_context():
    import structlog

    from app.core.telemetry import bind_context, clear_context, get_context

    clear_context()
    try:
        bind_context(
            task_id="task-probe",
            step_id="step-old",
            agent="agent-old",
            node_name="node-old",
        )
        bind_context(step_id=None, agent=None, node_name=None)

        assert get_context() == {"task_id": "task-probe"}
        assert structlog.contextvars.get_contextvars() == {"task_id": "task-probe"}
    finally:
        clear_context()


def test_worker_bootstrap_preserves_structured_logging_and_context():
    backend_dir = Path(__file__).resolve().parents[1]
    script = """
import logging

from celery.app.log import Logging

from app.core.telemetry import bind_context, get_logger
from app.tasks.celery_app import celery

Logging._setup = False
receivers = celery.log.setup_logging_subsystem(loglevel="INFO", colorize=False)
bind_context(task_id="task-probe", step_id="step-probe")
get_logger("worker.probe").info(
    "worker_logging_probe",
    hijack_root=celery.conf.worker_hijack_root_logger,
    setup_logging_receivers=len(receivers or []),
)
get_logger("worker.probe").debug("worker_debug_probe")
logging.getLogger("worker.stdlib").info("stdlib_logging_probe")
"""
    env = os.environ.copy()
    env.update(
        DATABASE_URL="sqlite://",
        LOG_FORMAT="json",
        LOG_LEVEL="debug",
        OTEL_EXPORTER_OTLP_ENDPOINT="",
        SENTRY_DSN="",
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    events = [json.loads(line) for line in result.stdout.strip().splitlines()]
    structured_event, debug_event, stdlib_event = events[-3:]
    assert structured_event["event"] == "worker_logging_probe"
    assert structured_event["logger"] == "worker.probe"
    assert structured_event["level"] == "info"
    assert structured_event["task_id"] == "task-probe"
    assert structured_event["step_id"] == "step-probe"
    assert structured_event["hijack_root"] is False
    assert structured_event["setup_logging_receivers"] >= 1
    assert debug_event["event"] == "worker_debug_probe"
    assert debug_event["level"] == "debug"
    assert stdlib_event["event"] == "stdlib_logging_probe"
    assert stdlib_event["logger"] == "worker.stdlib"
    assert stdlib_event["task_id"] == "task-probe"
    assert stdlib_event["step_id"] == "step-probe"
