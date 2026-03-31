"""
Voice Agent Billing — FastAPI application.
Wraps a voice/speech API with Mainlayer per-minute billing.
WebSocket endpoint streams audio while tracking session duration.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from session import SessionManager, Session
from mainlayer_billing import BillingClient, BillingError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

session_manager = SessionManager()
billing_client = BillingClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Voice Agent Billing starting...")
    yield
    # Close any lingering sessions on shutdown
    await session_manager.close_all()
    logger.info("Voice Agent Billing shut down.")


app = FastAPI(
    title="Voice Agent Billing",
    description="Voice agent API with Mainlayer per-minute billing",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request/Response Models ---

class StartSessionRequest(BaseModel):
    payment_token: str
    language: Optional[str] = "en-US"
    sample_rate: Optional[int] = 16000


class StartSessionResponse(BaseModel):
    session_id: str
    websocket_url: str
    message: str


class EndSessionResponse(BaseModel):
    session_id: str
    duration_seconds: float
    minutes_billed: int
    billing_summary: dict


class SessionStatusResponse(BaseModel):
    session_id: str
    active: bool
    duration_seconds: float
    minutes_billed: int


# --- HTTP Endpoints ---

@app.get("/health")
async def health():
    return {"status": "ok", "service": "voice-agent-billing"}


@app.post("/api/sessions/start", response_model=StartSessionResponse)
async def start_session(request: StartSessionRequest):
    """
    Start a new voice session. Verifies payment before creating the session.
    Returns a session_id and WebSocket URL for audio streaming.
    """
    resource_id = os.environ.get("MAINLAYER_RESOURCE_ID", "")
    if not resource_id:
        raise HTTPException(status_code=503, detail="Billing not configured")

    authorized = await billing_client.verify_access(resource_id, request.payment_token)
    if not authorized:
        raise HTTPException(
            status_code=402,
            detail="Payment required. Visit https://mainlayer.fr to add credits.",
        )

    session = await session_manager.create_session(
        payment_token=request.payment_token,
        language=request.language or "en-US",
        sample_rate=request.sample_rate or 16000,
    )

    host = os.environ.get("PUBLIC_HOST", "localhost:8000")
    ws_url = f"ws://{host}/api/sessions/{session.session_id}/stream"

    return StartSessionResponse(
        session_id=session.session_id,
        websocket_url=ws_url,
        message="Session started. Connect to the WebSocket to begin streaming.",
    )


@app.delete("/api/sessions/{session_id}", response_model=EndSessionResponse)
async def end_session(session_id: str):
    """
    End an active voice session and return the billing summary.
    Credits are deducted based on minutes used (rounded up).
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    summary = await session_manager.end_session(session_id, billing_client)
    return EndSessionResponse(**summary)


@app.get("/api/sessions/{session_id}", response_model=SessionStatusResponse)
async def get_session_status(session_id: str):
    """Return current status and billing info for an active session."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionStatusResponse(
        session_id=session_id,
        active=session.is_active,
        duration_seconds=session.duration_seconds,
        minutes_billed=session.minutes_billed,
    )


@app.get("/api/sessions")
async def list_sessions():
    """List all active sessions (admin endpoint)."""
    sessions = session_manager.list_active_sessions()
    return {
        "active_sessions": len(sessions),
        "sessions": [
            {
                "session_id": s.session_id,
                "duration_seconds": s.duration_seconds,
                "minutes_billed": s.minutes_billed,
            }
            for s in sessions
        ],
    }


# --- WebSocket Endpoint ---

@app.websocket("/api/sessions/{session_id}/stream")
async def audio_stream(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time audio streaming.

    Protocol:
      - Client sends audio chunks as binary frames
      - Server echoes back transcription/response as JSON text frames
      - Server sends periodic billing pings every 60 seconds
      - Client sends "end" as text to close gracefully

    Billing ticks every minute and deducts credits via Mainlayer.
    """
    session = session_manager.get_session(session_id)
    if not session:
        await websocket.close(code=4004, reason="Session not found")
        return

    if not session.is_active:
        await websocket.close(code=4003, reason="Session already ended")
        return

    await websocket.accept()
    logger.info(f"WebSocket connected for session {session_id}")

    billing_task = asyncio.create_task(
        _billing_tick_loop(session_id, session, websocket, billing_client)
    )

    try:
        while True:
            message = await asyncio.wait_for(websocket.receive(), timeout=300.0)

            if message["type"] == "websocket.disconnect":
                break

            if message.get("text") == "end":
                await websocket.send_json({"type": "session_ending", "session_id": session_id})
                break

            if message.get("bytes"):
                audio_chunk = message["bytes"]
                # --- Real speech processing goes here ---
                # In production: forward to Whisper, Deepgram, AssemblyAI, etc.
                transcription = f"[Transcribed {len(audio_chunk)} bytes]"
                await websocket.send_json({
                    "type": "transcription",
                    "text": transcription,
                    "session_id": session_id,
                    "duration_seconds": session.duration_seconds,
                })

    except asyncio.TimeoutError:
        logger.warning(f"Session {session_id} timed out after 5 minutes of inactivity")
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {session_id}")
    finally:
        billing_task.cancel()
        try:
            await billing_task
        except asyncio.CancelledError:
            pass

        summary = await session_manager.end_session(session_id, billing_client)
        logger.info(f"Session {session_id} ended: {summary}")
        try:
            await websocket.send_json({"type": "session_ended", "billing": summary})
        except Exception:
            pass


async def _billing_tick_loop(
    session_id: str,
    session: "Session",
    websocket: WebSocket,
    billing: BillingClient,
) -> None:
    """
    Deduct one minute of credits every 60 seconds while the session is active.
    Sends a billing_tick JSON message to the client each time.
    """
    resource_id = os.environ.get("MAINLAYER_RESOURCE_ID", "")
    try:
        while True:
            await asyncio.sleep(60)
            if not session.is_active:
                break

            try:
                charged = await billing.deduct_minute(resource_id, session.payment_token)
                session.increment_billed_minute()
                await websocket.send_json({
                    "type": "billing_tick",
                    "minutes_billed": session.minutes_billed,
                    "duration_seconds": session.duration_seconds,
                    "charged": charged,
                })
            except BillingError as e:
                logger.warning(f"Billing failed for session {session_id}: {e}")
                await websocket.send_json({
                    "type": "billing_error",
                    "message": str(e),
                })
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=os.environ.get("DEBUG", "false").lower() == "true",
    )
