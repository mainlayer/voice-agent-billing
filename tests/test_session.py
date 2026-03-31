"""
Tests for session.py — Session and SessionManager.
"""
import asyncio
import sys
import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from session import Session, SessionManager


# --- Session unit tests ---

def test_session_initial_state():
    s = Session(
        session_id="test-id",
        payment_token="tok",
        language="en-US",
        sample_rate=16000,
    )
    assert s.is_active is True
    assert s.minutes_billed == 0
    assert s.duration_seconds >= 0


def test_session_end_marks_inactive():
    s = Session(session_id="s1", payment_token="t", language="en", sample_rate=16000)
    assert s.is_active is True
    s.end()
    assert s.is_active is False
    assert s.ended_at is not None


def test_session_end_is_idempotent():
    s = Session(session_id="s1", payment_token="t", language="en", sample_rate=16000)
    s.end()
    ended_at = s.ended_at
    s.end()  # Second call should not change ended_at
    assert s.ended_at == ended_at


def test_session_duration_increases_over_time():
    s = Session(session_id="s1", payment_token="t", language="en", sample_rate=16000)
    d1 = s.duration_seconds
    time.sleep(0.05)
    d2 = s.duration_seconds
    assert d2 > d1


def test_session_duration_frozen_after_end():
    s = Session(session_id="s1", payment_token="t", language="en", sample_rate=16000)
    s.end()
    d1 = s.duration_seconds
    time.sleep(0.05)
    d2 = s.duration_seconds
    assert d1 == d2


def test_session_total_minutes_rounds_up():
    s = Session(session_id="s1", payment_token="t", language="en", sample_rate=16000)
    # Mock started_at so duration is 90 seconds = 2 minutes (ceil)
    s.started_at = time.monotonic() - 90
    assert s.total_minutes == 2


def test_session_increment_billed_minute():
    s = Session(session_id="s1", payment_token="t", language="en", sample_rate=16000)
    assert s.minutes_billed == 0
    s.increment_billed_minute()
    s.increment_billed_minute()
    assert s.minutes_billed == 2


# --- SessionManager tests ---

@pytest.mark.asyncio
async def test_session_manager_create_session():
    manager = SessionManager()
    session = await manager.create_session("token-xyz", "fr-FR", 8000)
    assert session.session_id
    assert session.language == "fr-FR"
    assert session.sample_rate == 8000
    assert session.is_active is True


@pytest.mark.asyncio
async def test_session_manager_get_session():
    manager = SessionManager()
    created = await manager.create_session("token-abc")
    retrieved = manager.get_session(created.session_id)
    assert retrieved is created


@pytest.mark.asyncio
async def test_session_manager_get_nonexistent_session():
    manager = SessionManager()
    assert manager.get_session("does-not-exist") is None


@pytest.mark.asyncio
async def test_session_manager_list_active_sessions():
    manager = SessionManager()
    s1 = await manager.create_session("t1")
    s2 = await manager.create_session("t2")
    s3 = await manager.create_session("t3")
    s3.end()

    active = manager.list_active_sessions()
    assert len(active) == 2
    assert s1 in active
    assert s2 in active
    assert s3 not in active


@pytest.mark.asyncio
async def test_session_manager_end_session_calls_billing():
    manager = SessionManager()

    mock_billing = MagicMock()
    mock_billing.deduct_minute = AsyncMock(return_value=True)

    session = await manager.create_session("payment-token")
    # Simulate 2 minutes elapsed
    session.started_at = time.monotonic() - 120

    with patch.dict(os.environ, {"MAINLAYER_RESOURCE_ID": "res_voice"}):
        summary = await manager.end_session(session.session_id, mock_billing)

    assert summary["session_id"] == session.session_id
    assert summary["duration_seconds"] >= 120
    assert "billing_summary" in summary
    # Should have billed 2 minutes
    assert mock_billing.deduct_minute.await_count == 2


@pytest.mark.asyncio
async def test_session_manager_end_session_removes_from_store():
    manager = SessionManager()
    session = await manager.create_session("token")
    sid = session.session_id

    mock_billing = MagicMock()
    mock_billing.deduct_minute = AsyncMock(return_value=True)

    with patch.dict(os.environ, {"MAINLAYER_RESOURCE_ID": "res_voice"}):
        await manager.end_session(sid, mock_billing)

    assert manager.get_session(sid) is None


@pytest.mark.asyncio
async def test_session_manager_end_nonexistent_session():
    manager = SessionManager()
    mock_billing = MagicMock()
    with pytest.raises(ValueError):
        await manager.end_session("ghost-session", mock_billing)


@pytest.mark.asyncio
async def test_session_manager_close_all():
    manager = SessionManager()
    s1 = await manager.create_session("t1")
    s2 = await manager.create_session("t2")
    await manager.close_all()
    assert manager.list_active_sessions() == []
