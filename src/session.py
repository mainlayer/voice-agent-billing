"""
Session management for the Voice Agent Billing service.
Tracks active voice sessions, their duration, and minutes billed.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from math import ceil
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """Represents an active voice billing session."""

    session_id: str
    payment_token: str
    language: str
    sample_rate: int
    started_at: float = field(default_factory=time.monotonic)
    ended_at: Optional[float] = None
    minutes_billed: int = 0
    is_active: bool = True

    @property
    def duration_seconds(self) -> float:
        """Elapsed time in seconds since session started."""
        end = self.ended_at if self.ended_at is not None else time.monotonic()
        return round(end - self.started_at, 2)

    @property
    def total_minutes(self) -> int:
        """Total minutes used, rounded up (for billing)."""
        return ceil(self.duration_seconds / 60)

    def increment_billed_minute(self) -> None:
        """Record that one additional minute has been billed."""
        self.minutes_billed += 1

    def end(self) -> None:
        """Mark the session as ended."""
        if self.is_active:
            self.ended_at = time.monotonic()
            self.is_active = False


class SessionManager:
    """
    In-memory store for active voice sessions.
    In production, replace with Redis or a database backend.
    """

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        payment_token: str,
        language: str = "en-US",
        sample_rate: int = 16000,
    ) -> Session:
        """Create and store a new session. Returns the Session object."""
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            payment_token=payment_token,
            language=language,
            sample_rate=sample_rate,
        )
        async with self._lock:
            self._sessions[session_id] = session

        logger.info(f"Created session {session_id} (lang={language})")
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Return a session by ID, or None if not found."""
        return self._sessions.get(session_id)

    def list_active_sessions(self) -> list[Session]:
        """Return all currently active sessions."""
        return [s for s in self._sessions.values() if s.is_active]

    async def end_session(
        self,
        session_id: str,
        billing_client,  # BillingClient — avoids circular import
    ) -> dict:
        """
        End a session, finalize billing for any unbilled partial minute,
        and return a billing summary dict.
        """
        import os
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        session.end()

        # Bill any remaining unbilled minutes
        total_minutes = session.total_minutes
        remaining = total_minutes - session.minutes_billed
        resource_id = os.environ.get("MAINLAYER_RESOURCE_ID", "")

        for _ in range(remaining):
            try:
                await billing_client.deduct_minute(resource_id, session.payment_token)
                session.increment_billed_minute()
            except Exception as e:
                logger.warning(f"Could not charge remaining minute for {session_id}: {e}")

        async with self._lock:
            self._sessions.pop(session_id, None)

        summary = {
            "session_id": session_id,
            "duration_seconds": session.duration_seconds,
            "minutes_billed": session.minutes_billed,
            "billing_summary": {
                "total_minutes": total_minutes,
                "minutes_charged": session.minutes_billed,
                "language": session.language,
            },
        }

        logger.info(
            f"Session {session_id} ended: "
            f"{session.duration_seconds:.1f}s, {session.minutes_billed} min billed"
        )
        return summary

    async def close_all(self) -> None:
        """Cancel all active sessions (called on shutdown)."""
        async with self._lock:
            for session in list(self._sessions.values()):
                session.end()
            self._sessions.clear()
        logger.info("All sessions closed")
