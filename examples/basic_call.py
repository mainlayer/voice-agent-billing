"""
Basic voice call example: start a session, stream audio, end session.

Demonstrates the full lifecycle:
  1. Start a session via HTTP (payment verified)
  2. Connect to WebSocket and send audio frames
  3. Receive transcription responses
  4. End the session and get a billing summary

Usage:
    export API_URL=http://localhost:8000
    export MAINLAYER_PAYMENT_TOKEN=your_payment_token
    python examples/basic_call.py
"""
import asyncio
import json
import os

import httpx
import websockets

API_URL = os.environ.get("API_URL", "http://localhost:8000")
PAYMENT_TOKEN = os.environ.get("MAINLAYER_PAYMENT_TOKEN", "demo-token")


def generate_fake_audio(duration_seconds: int = 3, sample_rate: int = 16000) -> bytes:
    """Generate fake PCM audio bytes for demo purposes."""
    num_samples = duration_seconds * sample_rate
    return bytes([0] * (num_samples * 2))  # 16-bit PCM, zeroed


async def main():
    print("=== Voice Agent Billing — Basic Call Demo ===\n")

    async with httpx.AsyncClient(base_url=API_URL) as client:
        # 1. Start a session
        print("Starting voice session...")
        resp = await client.post(
            "/api/sessions/start",
            json={"payment_token": PAYMENT_TOKEN, "language": "en-US", "sample_rate": 16000},
        )

        if resp.status_code == 402:
            print("Payment required: add credits at https://mainlayer.fr")
            return
        resp.raise_for_status()

        data = resp.json()
        session_id = data["session_id"]
        ws_url = data["websocket_url"]
        print(f"Session started: {session_id}")
        print(f"WebSocket URL:  {ws_url}\n")

        # 2. Connect to WebSocket and stream audio
        print("Connecting to audio stream...")
        try:
            async with websockets.connect(ws_url) as ws:
                print("Connected. Sending audio chunks...\n")

                # Send 3 chunks of fake audio
                for i in range(3):
                    audio_chunk = generate_fake_audio(duration_seconds=1)
                    await ws.send(audio_chunk)
                    print(f"Sent audio chunk {i + 1} ({len(audio_chunk)} bytes)")

                    # Wait for transcription response
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        parsed = json.loads(msg)
                        if parsed.get("type") == "transcription":
                            print(f"Transcription: {parsed.get('text')}")
                            print(f"Duration so far: {parsed.get('duration_seconds')}s\n")
                    except asyncio.TimeoutError:
                        print("(No response — server may be processing)\n")
                    except Exception as e:
                        print(f"WebSocket error: {e}")
                        break

                # Send end signal
                await ws.send("end")
                print("Sent 'end' signal")

                # Receive session_ended message
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    parsed = json.loads(msg)
                    if parsed.get("type") == "session_ended":
                        billing = parsed.get("billing", {})
                        print(f"\n=== Session Ended ===")
                        print(f"Duration:       {billing.get('duration_seconds')}s")
                        print(f"Minutes billed: {billing.get('minutes_billed')}")
                        print(f"Summary:        {billing.get('billing_summary')}")
                except asyncio.TimeoutError:
                    print("Timed out waiting for session_ended message")

        except (ConnectionRefusedError, OSError) as e:
            print(f"Could not connect to WebSocket: {e}")
            print("Make sure the server is running: uvicorn src.main:app --reload")

        # 3. Confirm session ended via HTTP
        status = await client.get(f"/api/sessions/{session_id}")
        if status.status_code == 404:
            print("\nSession successfully closed (not found = already removed).")
        else:
            print(f"\nSession status: {status.json()}")


if __name__ == "__main__":
    asyncio.run(main())
