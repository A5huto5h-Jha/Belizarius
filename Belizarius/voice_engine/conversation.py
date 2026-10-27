import traceback
import asyncio
import os
import queue
from pathlib import Path
from scipy.signal import resample_poly
import numpy as np
import sounddevice as sd
from dotenv import load_dotenv
from google import genai
from google.genai import types
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent / "Belizarius_Workspace"
WORKSPACE.mkdir(exist_ok=True)

def safe_path(name: str) -> Path:
    """Allow file access only inside Belizarius_Workspace."""
    path = (WORKSPACE / name).resolve()

    if path != WORKSPACE.resolve() and WORKSPACE.resolve() not in path.parents:
        raise ValueError("Access denied: outside Belizarius_Workspace")

    return path


def create_file(name: str, content: str = "") -> str:
    path = safe_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Created {name}"


def read_file(name: str) -> str:
    path = safe_path(name)
    if not path.is_file():
        return f"File not found: {name}"
    return path.read_text(encoding="utf-8")[:20000]


def write_file(name: str, content: str) -> str:
    path = safe_path(name)
    if not path.is_file():
        return f"File not found: {name}. Use create_file first."
    path.write_text(content, encoding="utf-8")
    return f"Updated {name}"


def delete_file(name: str) -> str:
    path = safe_path(name)
    if not path.is_file():
        return f"File not found: {name}"
    path.unlink()
    return f"Deleted {name}"


def open_file(name: str) -> str:
    path = safe_path(name)
    if not path.is_file():
        return f"File not found: {name}"
    os.startfile(str(path))  # Windows
    return f"Opened {name}"
load_dotenv(ROOT.parent / ".env")

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "gemini-3.8-live"

# Microphone capture: use the working WASAPI device.
DEVICE_RATE = 48000
SAMPLE_RATE_IN = 16000
SAMPLE_RATE_OUT = 48000
BLOCK_SIZE = 4800

# Use the same working microphone device as wake_sherpa.py.
DEVICE_ID = 21

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

        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)

        samples_16k = resample_poly(
            samples,
            up=1,
            down=3,
        )

        chunk_16k = np.clip(
            samples_16k,
            -32768,
            32767,
        ).astype(np.int16).tobytes()
        await session.send_realtime_input(
            audio=types.Blob(
                data=chunk_16k,
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
            tool_call = response.tool_call

            if tool_call:
                results = []

                for call in tool_call.function_calls:
                    args = dict(call.args or {})
                    name = call.name

                    try:
                        if name == "create_file":
                            result = create_file(**args)
                        elif name == "read_file":
                            result = read_file(**args)
                        elif name == "write_file":
                            result = write_file(**args)
                        elif name == "open_file":
                            result = open_file(**args)
                        elif name == "delete_file":
                            # Temporary safety guard: do not delete yet.
                            result = (
                                "Deletion is disabled until the app obtains "
                                "explicit user confirmation."
                            )
                        else:
                            result = f"Unknown tool: {name}"

                    except Exception as exc:
                        result = f"Tool failed: {type(exc).__name__}: {exc}"
                        log(f"ERROR: {type(exc).__name__}: {exc}")
                        traceback.print_exc()

                    log(f"TOOL_RESULT: {name}: {result}")

                    results.append(
                        types.FunctionResponse(
                            id=call.id,
                            name=name,
                            response={"result": result},
                        )
                    )
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
                        audio_bytes = part.inline_data.data

                        # Gemini Live output is typically 24 kHz PCM.
                        samples_24k = np.frombuffer(
                            audio_bytes, dtype=np.int16
                        )

                        # Convert 24 kHz to the speaker's 48 kHz rate.
                        samples_48k = resample_poly(
                            samples_24k, up=2, down=1
                        )

                        speaker.write(
                            np.clip(samples_48k, -32768, 32767)
                            .astype(np.int16)
                            .tobytes()
                        )
            if content.turn_complete:
                log("TURN_COMPLETE")


async def main():
    FILE_TOOLS = [
    types.FunctionDeclaration(
        name="create_file",
        description="Create a text file in the workspace with supplied content.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING", "description": "Relative file path"},
                "content": {"type": "STRING", "description": "Initial file content"},
            },
            "required": ["name", "content"],
        },
    ),
    types.FunctionDeclaration(
        name="read_file",
        description="Read a text file from the workspace.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING", "description": "Relative file path"},
            },
            "required": ["name"],
        },
    ),
    types.FunctionDeclaration(
        name="write_file",
        description="Replace the contents of an existing workspace text file.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING"},
                "content": {"type": "STRING"},
            },
            "required": ["name", "content"],
        },
    ),
    types.FunctionDeclaration(
        name="delete_file",
        description="Delete a file from the workspace. Only call after explicit user confirmation.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING"},
            },
            "required": ["name"],
        },
    ),
    types.FunctionDeclaration(
        name="open_file",
        description="Open a workspace file using its default Windows application.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING"},
            },
            "required": ["name"],
        },
    ),
]
    global running

    if not API_KEY or API_KEY == "PASTE_YOUR_API_KEY_HERE":
        log("ERROR: GEMINI_API_KEY is missing from the root .env file.")
        return

    client = genai.Client(api_key=API_KEY)

    config = {
        "response_modalities": ["AUDIO"],
        "input_audio_transcription": {},
        "output_audio_transcription": {},

        # Tools belong at the TOP LEVEL of config.
        "tools": [
            types.Tool(function_declarations=FILE_TOOLS)
        ],

        # Keep the existing voice settings nested here.
        "speech_config": {
            "voice_config": {
                "prebuilt_voice_config": {
                    "voice_name": "Algenib"
                }
            }
        },

        # Keep your full existing voice/personality prompt here.
        "system_instruction": (
            "You are Belizarius, a battle-hardened Roman soldier and commander. "
            "Speak English with a strong, deep, commanding Latin-influenced accent. "
            "Use the available file tools when the user requests file operations. "
            "Never claim an operation succeeded until its tool result confirms it. "
            "Ask for explicit confirmation before deleting files. "
            "Only access files through the supplied tools."
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
                samplerate=DEVICE_RATE,
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
                try:
                    await asyncio.gather(sender, receiver)
                finally:
                    running = False

                    sender.cancel()
                    receiver.cancel()

                    await asyncio.gather(
                        sender,
                        receiver,
                        return_exceptions=True,
                    )
                
                
                

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
