# Voice Agent Billing — Mainlayer

[![CI](https://github.com/mainlayer/voice-agent-billing/actions/workflows/ci.yml/badge.svg)](https://github.com/mainlayer/voice-agent-billing/actions)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)

WebSocket-based voice agent API with per-minute billing via Mainlayer. Stream audio over WebSocket, automatic per-minute credit deduction, and real-time billing updates.

**Why Mainlayer?** Voice APIs are expensive and minute-based. Mainlayer lets you pass cost directly to users with zero billing infrastructure: one API call deducts a minute of credits, automatically. Sessions start only when payment is verified.

## Quick Start

### Installation

```bash
git clone https://github.com/mainlayer/voice-agent-billing
cd voice-agent-billing
pip install -e ".[dev]"
```

### Development (No API Key)

```bash
# Run without Mainlayer integration (billing mocked)
uvicorn src.main:app --reload --port 8000
```

### Production (With Mainlayer API Key)

```bash
export MAINLAYER_API_KEY=sk_test_...
export MAINLAYER_RESOURCE_ID=res_voice_001
uvicorn src.main:app --reload --port 8000
```

### Run the Example

```bash
export MAINLAYER_PAYMENT_TOKEN=tok_test_...
python examples/basic_call.py
```

## API Overview

### HTTP Endpoints

#### 1. Start a Session

**Request:**
```
POST /api/sessions/start
Content-Type: application/json

{
  "payment_token": "tok_user_abc123",
  "language": "en-US",
  "sample_rate": 16000
}
```

**Response (200 OK):**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "websocket_url": "ws://localhost:8000/api/sessions/550e8400-e29b-41d4-a716-446655440000/stream",
  "message": "Session started. Connect to the WebSocket to begin streaming."
}
```

**Errors:**
- `402 Payment Required` — Insufficient credits
- `503 Service Unavailable` — Billing not configured

#### 2. Get Session Status

**Request:**
```
GET /api/sessions/{session_id}
```

**Response (200 OK):**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "active": true,
  "duration_seconds": 45.3,
  "minutes_billed": 1
}
```

#### 3. End a Session

**Request:**
```
DELETE /api/sessions/{session_id}
```

**Response (200 OK):**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "duration_seconds": 123.4,
  "minutes_billed": 3,
  "billing_summary": {
    "start_time": "2026-03-31T14:22:10Z",
    "end_time": "2026-03-31T14:24:53Z",
    "total_cost_usd": 0.30,
    "cost_per_minute_usd": 0.10,
    "breakdown": {
      "minute_1": "0.10",
      "minute_2": "0.10",
      "minute_3": "0.10"
    }
  }
}
```

#### 4. List Active Sessions

**Request:**
```
GET /api/sessions
```

**Response (200 OK):**
```json
{
  "active_sessions": [
    {
      "session_id": "550e8400-e29b-41d4-a716-446655440000",
      "duration_seconds": 45.3,
      "minutes_billed": 1
    }
  ],
  "total_active": 1
}
```

#### 5. Health Check

**Request:**
```
GET /health
```

**Response:**
```json
{
  "status": "ok",
  "service": "voice-agent-billing"
}
```

### WebSocket Endpoint

**Connect to:** `ws://host/api/sessions/{session_id}/stream`

After `POST /api/sessions/start` returns a `session_id`, connect to the WebSocket URL to stream audio.

#### Messages from Client → Server

**Binary frames:** Raw PCM/audio bytes (16-bit, mono, sample_rate specified at session start)

```javascript
const socket = new WebSocket(websocket_url);
socket.binaryType = 'arraybuffer';

// Send 16KB audio chunk (100ms at 16kHz)
const audioChunk = new Uint8Array(16000 * 2 / 10); // ~100ms at 16kHz
socket.send(audioChunk);
```

**Text message:** `"end"` to gracefully close the session

```javascript
socket.send("end");
```

#### Messages from Server → Client

**Transcription:**
```json
{
  "type": "transcription",
  "text": "What is the weather today?",
  "duration_seconds": 12.4,
  "confidence": 0.95
}
```

**Per-Minute Billing Update (every 60 seconds):**
```json
{
  "type": "billing_tick",
  "minutes_billed": 1,
  "duration_seconds": 60.1,
  "cost_so_far": 0.10,
  "charged": true
}
```

**Session Ended:**
```json
{
  "type": "session_ended",
  "duration_seconds": 123.4,
  "minutes_billed": 3,
  "total_cost_usd": 0.30,
  "billing": {
    "duration_seconds": 123.4,
    "minutes_billed": 3
  }
}
```

**Error:**
```json
{
  "type": "error",
  "message": "Insufficient credits. Session terminated.",
  "code": "billing_error"
}
```

## Usage Examples

### Python Client

```python
import asyncio
import websockets
import httpx

async def run_voice_session():
    async with httpx.AsyncClient() as client:
        # 1. Start session
        resp = await client.post(
            "http://localhost:8000/api/sessions/start",
            json={
                "payment_token": "tok_test_...",
                "language": "en-US",
                "sample_rate": 16000
            }
        )
        session = resp.json()
        session_id = session["session_id"]
        ws_url = session["websocket_url"]

        # 2. Connect WebSocket
        async with websockets.connect(ws_url) as ws:
            # Stream audio
            with open("audio.wav", "rb") as f:
                # Read 100ms chunks at 16kHz
                chunk_size = 16000 * 2 // 10
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    await ws.send(chunk)

            # Get transcriptions
            async for msg_raw in ws:
                if isinstance(msg_raw, bytes):
                    continue

                import json
                msg = json.loads(msg_raw)

                if msg["type"] == "transcription":
                    print(f"User said: {msg['text']}")
                elif msg["type"] == "billing_tick":
                    print(f"Billed {msg['minutes_billed']} minute(s): ${msg['cost_so_far']}")
                elif msg["type"] == "session_ended":
                    print(f"Total cost: ${msg['total_cost_usd']}")
                    break

asyncio.run(run_voice_session())
```

### JavaScript/Browser

```javascript
async function startVoiceCall() {
  // 1. Request session
  const sessionRes = await fetch('/api/sessions/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      payment_token: 'tok_user_...',
      language: 'en-US',
      sample_rate: 16000
    })
  });

  const { session_id, websocket_url } = await sessionRes.json();

  // 2. Connect WebSocket
  const ws = new WebSocket(websocket_url);
  ws.binaryType = 'arraybuffer';

  // 3. Stream audio from microphone
  const audioContext = new (window.AudioContext || window.webkitAudioContext)();
  const mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const source = audioContext.createMediaStreamSource(mediaStream);

  const processor = audioContext.createScriptProcessor(4096, 1, 1);
  source.connect(processor);
  processor.connect(audioContext.destination);

  processor.onaudioprocess = (event) => {
    const channelData = event.inputBuffer.getChannelData(0);
    const int16Data = new Int16Array(channelData.length);
    for (let i = 0; i < channelData.length; i++) {
      int16Data[i] = channelData[i] < 0
        ? channelData[i] * 0x8000
        : channelData[i] * 0x7FFF;
    }
    ws.send(int16Data.buffer);
  };

  // 4. Handle messages
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === 'transcription') {
      console.log('User said:', msg.text);
    } else if (msg.type === 'billing_tick') {
      console.log(`Billed: ${msg.minutes_billed} minute(s)`);
    } else if (msg.type === 'session_ended') {
      console.log(`Total cost: $${msg.total_cost_usd}`);
      ws.close();
    }
  };

  // 5. End gracefully
  document.getElementById('end-call').onclick = () => {
    ws.send('end');
  };
}
```

## Session Lifecycle

```
POST /api/sessions/start
  ↓
[Mainlayer: verify_access(resource_id, payment_token)]
  ↓ authorized?
No  → Return 402 Payment Required
  ↓
Yes → Create session, return session_id + WebSocket URL
  ↓
[Client connects to WebSocket]
  ↓
Every 60 seconds:
  ↓
  [Mainlayer: deduct_minute(resource_id, payment_token)]
  ↓ sufficient credits?
  No  → Send error message, close session
  ↓
Yes → Send billing_tick, continue streaming
  ↓
[Client sends "end" or disconnects]
  ↓
[Mainlayer: deduct partial minute (if any)]
  ↓
Return session summary with total cost
```

## Billing Model

- **Per-minute billing**: Each minute (or partial minute) costs $0.10
- **Verification at start**: Payment verified before session creation
- **Periodic checks**: Every 60 seconds, one minute is deducted
- **Graceful degradation**: If credits run out mid-session, user is notified and session ends
- **Partial minute billing**: Session ending at 1:23 is billed as 2 minutes

### Example Billing Breakdown

```
Session duration: 2 minutes 45 seconds
Minutes billed: 3 (rounded up)
Cost per minute: $0.10
Total cost: $0.30

Timeline:
  0:00 - Session starts, payment verified
  1:00 - First minute billed ($0.10), billing_tick sent
  2:00 - Second minute billed ($0.10), billing_tick sent
  2:45 - Session ends
  2:45 - Third minute billed ($0.10) for partial minute
  Total: 3 × $0.10 = $0.30
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MAINLAYER_API_KEY` | Yes* | — | Mainlayer API key |
| `MAINLAYER_RESOURCE_ID` | Yes* | — | Resource ID for per-minute billing |
| `MAINLAYER_API_URL` | No | https://api.mainlayer.fr | Mainlayer API endpoint |
| `PUBLIC_HOST` | No | localhost:8000 | Public host:port for WebSocket URLs |
| `ALLOWED_ORIGINS` | No | * | CORS origins (comma-separated) |
| `HOST` | No | 0.0.0.0 | Server host |
| `PORT` | No | 8000 | Server port |
| `LOG_LEVEL` | No | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |

*Required for production; optional in development.

## Speech Recognition Integration

The service includes a stub for speech recognition. Replace the stub to integrate with real speech-to-text APIs:

### OpenAI Whisper

```python
import openai

async def transcribe_audio(audio_bytes):
    """Transcribe audio using OpenAI Whisper."""
    response = await openai.Audio.atranscribe(
        model="whisper-1",
        file=("audio.wav", audio_bytes),
        language="en"
    )
    return response["text"]
```

### Deepgram

```python
from deepgram import Deepgram

async def transcribe_audio(audio_bytes, language="en"):
    """Transcribe audio using Deepgram."""
    dg = Deepgram(os.environ["DEEPGRAM_API_KEY"])
    response = await dg.transcription.prerecorded(
        {"buffer": audio_bytes, "mimetype": "audio/wav"},
        {"language": language, "model": "nova-2"}
    )
    return response["results"]["channels"][0]["alternatives"][0]["transcript"]
```

### AssemblyAI

```python
import aiohttp

async def transcribe_audio(audio_bytes):
    """Transcribe audio using AssemblyAI."""
    async with aiohttp.ClientSession() as session:
        # Upload audio
        async with session.post(
            "https://api.assemblyai.com/v2/upload",
            data=audio_bytes,
            headers={"Authorization": os.environ["ASSEMBLYAI_API_KEY"]}
        ) as upload_resp:
            audio_url = (await upload_resp.json())["upload_url"]

        # Request transcription
        async with session.post(
            "https://api.assemblyai.com/v2/transcript",
            json={"audio_url": audio_url},
            headers={"Authorization": os.environ["ASSEMBLYAI_API_KEY"]}
        ) as transcribe_resp:
            return (await transcribe_resp.json())["text"]
```

## Production Deployment

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -e .

ENV MAINLAYER_API_KEY=sk_prod_...
ENV MAINLAYER_RESOURCE_ID=res_voice_prod
ENV PUBLIC_HOST=voice.example.com
ENV ALLOWED_ORIGINS=https://example.com,https://app.example.com

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: voice-agent-billing
spec:
  replicas: 3
  selector:
    matchLabels:
      app: voice-agent-billing
  template:
    metadata:
      labels:
        app: voice-agent-billing
    spec:
      containers:
      - name: voice-agent
        image: voice-agent-billing:latest
        ports:
        - containerPort: 8000
        env:
        - name: MAINLAYER_API_KEY
          valueFrom:
            secretKeyRef:
              name: mainlayer-secrets
              key: api-key
        - name: MAINLAYER_RESOURCE_ID
          value: res_voice_prod
        - name: PUBLIC_HOST
          value: voice.example.com
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
```

### Production Checklist

- [ ] Set `MAINLAYER_API_KEY` to production key
- [ ] Set `MAINLAYER_RESOURCE_ID` to production resource
- [ ] Configure `PUBLIC_HOST` to match domain
- [ ] Set `ALLOWED_ORIGINS` to trusted domains only
- [ ] Enable HTTPS (via reverse proxy, e.g., Nginx, Cloudflare)
- [ ] Set up structured logging (JSON format)
- [ ] Add request rate limiting
- [ ] Monitor WebSocket connections
- [ ] Set up alerts for billing errors
- [ ] Replace speech stub with real API
- [ ] Test graceful session shutdown
- [ ] Add authentication (OAuth2, JWT)

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/test_session.py::test_billing_tick -v

# With coverage
pytest tests/ --cov=src --cov-report=html
```

## Architecture

- **FastAPI** — HTTP endpoints for session management
- **WebSocket** — Real-time audio streaming and billing updates
- **Session Manager** — In-memory session tracking (replace with Redis/DB in production)
- **Billing Client** — Mainlayer API integration for per-minute deduction
- **Async-native** — All operations fully async with proper lock management

## Troubleshooting

### WebSocket Connection Refused

- Ensure server is running on the correct host/port
- Check `PUBLIC_HOST` environment variable
- Verify CORS origins are configured correctly

### Payment Verification Failed

- Verify `MAINLAYER_API_KEY` is set
- Check `MAINLAYER_RESOURCE_ID` is valid
- Ensure payment token is active and has credits

### Billing Tick Not Received

- Check WebSocket is fully connected before sending audio
- Verify server logging for errors
- Ensure session hasn't been terminated

## Support

- **Docs**: https://docs.mainlayer.fr
- **API**: https://api.mainlayer.fr
- **Dashboard**: https://dashboard.mainlayer.fr
- **Issues**: https://github.com/mainlayer/voice-agent-billing/issues
