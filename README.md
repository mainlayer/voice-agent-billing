# voice-agent-billing

![CI](https://github.com/mainlayer/voice-agent-billing/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

**Voice agent API with Mainlayer per-minute billing — stream audio over WebSocket and charge users by the minute.**

## Why Mainlayer?

Voice APIs are expensive and minute-based. Mainlayer lets you pass that cost directly to users with zero billing infrastructure: one API call deducts a minute of credits, automatically. Sessions start only when payment is verified.

## Installation

```bash
pip install mainlayer
```

## Quickstart

```bash
git clone https://github.com/mainlayer/voice-agent-billing
cd voice-agent-billing
pip install -e ".[dev]"

export MAINLAYER_API_KEY=your_api_key
export MAINLAYER_RESOURCE_ID=your_resource_id

cd src && uvicorn main:app --reload
```

Run the example:

```bash
export MAINLAYER_PAYMENT_TOKEN=your_token
python examples/basic_call.py
```

## Key Features

- **Per-Minute Billing** — Mainlayer deducts one credit per minute, automatically
- **Session Management** — track active calls, duration, and billing state in memory
- **WebSocket Audio Streaming** — real-time binary audio frame ingestion
- **Payment Verified at Session Start** — no session created without valid payment
- **Graceful End** — session summary returned on disconnect with full billing breakdown
- **Billing Tick Messages** — clients receive billing updates every 60 seconds
- **Plug-in Speech Backend** — swap in Whisper, Deepgram, or AssemblyAI

## Project Structure

```
voice-agent-billing/
├── src/
│   ├── main.py                # FastAPI app — HTTP + WebSocket endpoints
│   ├── session.py             # Session + SessionManager (duration tracking)
│   └── mainlayer_billing.py   # BillingClient — verify access + deduct minutes
├── examples/
│   └── basic_call.py          # Start session, stream audio, receive billing summary
├── tests/
│   ├── test_session.py        # Session lifecycle tests
│   └── test_billing.py        # BillingClient tests (fully mocked)
├── .github/workflows/ci.yml
└── pyproject.toml
```

## API Reference

### HTTP Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/sessions/start` | Start session, verify payment, get WebSocket URL |
| DELETE | `/api/sessions/{id}` | End session, get billing summary |
| GET | `/api/sessions/{id}` | Get session status |
| GET | `/api/sessions` | List all active sessions |

### WebSocket

**Endpoint:** `ws://host/api/sessions/{session_id}/stream`

**Frames sent by client:**
- Binary frames: raw PCM/audio bytes
- Text `"end"`: gracefully close the session

**Frames received by client:**

```json
// Audio transcription
{"type": "transcription", "text": "...", "duration_seconds": 12.4}

// Per-minute billing update
{"type": "billing_tick", "minutes_billed": 1, "duration_seconds": 60.1, "charged": true}

// Session closed
{"type": "session_ended", "billing": {"duration_seconds": 73.2, "minutes_billed": 2}}
```

### `POST /api/sessions/start`

```json
{
  "payment_token": "your-mainlayer-token",
  "language": "en-US",
  "sample_rate": 16000
}
```

**Response:**
```json
{
  "session_id": "uuid",
  "websocket_url": "ws://host/api/sessions/uuid/stream",
  "message": "Session started. Connect to the WebSocket to begin streaming."
}
```

## Billing Flow

```
POST /api/sessions/start
    ↓
[Mainlayer: verify_access(resource_id, payment_token)]
    ↓ authorized?
No  → 402 Payment Required
Yes → create session, return WebSocket URL
    ↓
[WebSocket open — audio stream begins]
    ↓
Every 60s → deduct_minute(resource_id, payment_token)
    ↓ insufficient credits?
Yes → billing_error message sent to client
    ↓
Client sends "end" or disconnects
    ↓
Remaining partial minute billed
Session summary returned
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MAINLAYER_API_KEY` | Yes | Your Mainlayer API key |
| `MAINLAYER_RESOURCE_ID` | Yes | Resource ID for per-minute billing |
| `PUBLIC_HOST` | No | Host:port for WebSocket URLs (default: `localhost:8000`) |
| `ALLOWED_ORIGINS` | No | CORS origins (default: `*`) |
| `PORT` | No | Server port (default: 8000) |

## Integrating a Real Speech API

Replace the stub in `main.py`'s WebSocket handler:

```python
# In _audio_stream, replace the transcription stub:
transcription = await your_speech_client.transcribe(audio_chunk)
```

Supported backends: OpenAI Whisper, Deepgram, AssemblyAI, Google Speech-to-Text.

📚 Full docs at [mainlayer.fr](https://mainlayer.fr)
