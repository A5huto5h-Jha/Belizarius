
import asyncio
import os
import queue
from pathlib import Path

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "gemini-3.8-live"

SAMPLE_RATE_IN = 16000
SAMPLE_RATE_OUT = 24000
BLOCK_SIZE = 1600

# Same microphone device as wake_sherpa.py
DEVICE_ID = 1

audio_queue = queue.Queue(maxsize=30)
running = True
callback_count = 0


def log(message):
    print(message, flush=True)


def audio_callback(indata, frames, time_info, status):
    """Capture microphone audio and report its volume."""
    global callback_count

    if status:
        log(f"MIC_STATUS: {status}")

    raw_audio = bytes(indata)

    try:
        audio_queue.put_nowait(raw_audio)
    except queue.Full:
        try:
            audio_queue.get_nowait()
            audio_queue.put_nowait(raw_audio)
        except queue.Empty:
            pass

    # Report microphone volume roughly once per second.
    callback_count += 1
    if callback_count % 10 == 0:
        samples = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32)
        if samples.size:
            rms = float(np.sqrt(np.mean(samples ** 2)))
            log(f"MIC_LEVEL: {rms:.0f}")


async def send_microphone_audio(session):
    """Send captured microphone chunks to Gemini."""
    while running:
        try:
            chunk = await asyncio.to_thread(audio_queue.get, True, 0.5)
        except queue.Empty:
            continue

        await session.send_realtime_input(
            audio=types.Blob(
                data=chunk,
                mime_type="audio/pcm;rate=16000",
            )
        )


async def receive_gemini_audio(session):
    """Print transcriptions and play Gemini's spoken response."""
    global running

    with sd.RawOutputStream(
        samplerate=SAMPLE_RATE_OUT,
        channels=1,
        dtype="int16",
    ) as speaker:
        log("SPEAKER_READY")

        async for response in session.receive():
            if not running:
                break

            content = response.server_content
            if content is None:
                continue

            if content.input_transcription:
                text = content.input_transcription.text
                if text:
                    log(f"YOU SAID: {text}")

            if content.output_transcription:
                text = content.output_transcription.text
                if text:
                    log(f"BELIZARIUS: {text}")

            if content.model_turn:
                for part in content.model_turn.parts:
                    if part.inline_data and part.inline_data.data:
                        speaker.write(part.inline_data.data)

            if content.turn_complete:
                log("TURN_COMPLETE")


async def main():
    global running

    if not API_KEY or API_KEY == "PASTE_YOUR_API_KEY_HERE":
        log("ERROR: GEMINI_API_KEY is missing from the root .env file.")
        return

    client = genai.Client(api_key=API_KEY)

    config = {
        "response_modalities": ["AUDIO"],
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "speech_config": {
            "voice_config": {
                "prebuilt_voice_config": {
                    "voice_name": "Algenib"
                }
            }
        },
        "system_instruction": (
            "You are Belizarius, a battle-hardened Roman soldier and commander. "
            "Speak English with a STRONG, unmistakable Latin-influenced accent, "
            "inspired by a Roman commander in a historical epic. The accent must "
            "be clearly audible, not merely implied by your choice of words. "
            "Use firm, deliberate syllables, strong consonants, rounded vowels, "
            "slightly rolled R sounds where natural, and a measured, weighty cadence. "
            "Avoid sounding like a native American or British English speaker. "
            "Do not use a modern exaggerated Italian stereotype. "
            "Your voice is deep, gravelly, masculine, stern, and commanding, "
            "with restrained anger and occasional intimidating emphasis. "
            "Speak as if addressing soldiers before battle. Use natural English "
            "grammar and pronunciation; do not speak Latin unless asked. "
            "Keep replies concise and authoritative."
        ),
    }

    try:
        log("CONNECTING_TO_GEMINI")

        async with client.aio.live.connect(
            model=MODEL,
            config=config,
        ) as session:
            log("GEMINI_CONNECTED")

            # IMPORTANT: actually open the microphone.
            with sd.RawInputStream(
                samplerate=SAMPLE_RATE_IN,
                blocksize=BLOCK_SIZE,
                device=DEVICE_ID,
                dtype="int16",
                channels=1,
                callback=audio_callback,
            ):
                log("MICROPHONE_READY: Speak now.")
                log("MIC_LEVEL should increase when you speak.")

                sender = asyncio.create_task(
                    send_microphone_audio(session)
                )
                receiver = asyncio.create_task(
                    receive_gemini_audio(session)
                )

                done, pending = await asyncio.wait(
                    [sender, receiver],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                running = False

                for task in pending:
                    task.cancel()

                await asyncio.gather(*pending, return_exceptions=True)

                for task in done:
                    error = task.exception()
                    if error:
                        raise error

    except Exception as error:
        running = False
        log(f"ERROR: {type(error).__name__}: {error}")
    finally:
        client.close()
        log("CONVERSATION_STOPPED")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        running = False
        print("\nStopped.", flush=True)
