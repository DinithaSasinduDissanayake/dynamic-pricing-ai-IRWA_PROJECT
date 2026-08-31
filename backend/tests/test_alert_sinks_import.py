import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from core.agents.alert_service.util.retry import retry
from core.agents.alert_service.sinks.email import EmailSink
from core.agents.alert_service.sinks.slack import SlackSink
from core.agents.alert_service.sinks.webhook import WebhookSink
from core.agents.alert_service.sinks.ui import UiSink
from core.agents.alert_service.sinks import get_sinks


def test_import_all_alert_sinks():
    """Verify that all alert sinks can be imported and instantiated via get_sinks()."""
    assert EmailSink is not None
    assert SlackSink is not None
    assert WebhookSink is not None
    assert UiSink is not None

    sinks = get_sinks(repo=None)
    assert isinstance(sinks, dict)
    assert "ui" in sinks
    assert "email" in sinks
    assert "slack" in sinks
    assert "webhook" in sinks
    assert isinstance(sinks["ui"], UiSink)
    assert isinstance(sinks["email"], EmailSink)
    assert isinstance(sinks["slack"], SlackSink)
    assert isinstance(sinks["webhook"], WebhookSink)


@pytest.mark.asyncio
async def test_retry_helper_retries_n_times_then_raises():
    """Verify that retry helper retries N times and raises on the Nth attempt."""
    call_count = 0

    async def failing_operation():
        nonlocal call_count
        call_count += 1
        raise ValueError(f"Failure on attempt {call_count}")

    with pytest.raises(ValueError) as exc_info:
        await retry(failing_operation, attempts=3, delay=0.0)

    assert call_count == 3
    assert "Failure on attempt 3" in str(exc_info.value)


@pytest.mark.asyncio
async def test_retry_helper_succeeds_after_transient_failure():
    """Verify that retry helper succeeds if a subsequent attempt succeeds."""
    call_count = 0

    async def transient_operation():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError(f"Temporary failure {call_count}")
        return "success"

    result = await retry(transient_operation, attempts=4, delay=0.0)
    assert result == "success"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_helper_sync_function():
    """Verify that retry helper also supports synchronous callables."""
    call_count = 0

    def sync_failing():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise RuntimeError("sync fail")
        return 42

    result = await retry(sync_failing, attempts=3, delay=0.0)
    assert result == 42
    assert call_count == 2
