"""
Belizarius continuous voice conversation engine.

Features:
- Persistent Gemini Live session and continuous microphone sending.
- Correctly returns tool results to Gemini, allowing spoken completion reports.
- Concurrent execution of independent tool calls.
- Low-latency, chunked playback with queue clearing on interruption.
- Workspace-restricted file operations, website opening, YouTube search, and email drafting.
"""
import asyncio
import os
import queue
import threading
import traceback
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
import time

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly
from dotenv import load_dotenv
from google import genai
from google.genai import types

import os_tools


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
load_dotenv(PROJECT_ROOT / ".env")

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")

# Tested AMD WASAPI microphone.
DEVICE_ID = 21
DEVICE_RATE = 48000
INPUT_RATE = 16000
OUTPUT_RATE = 48000
# Conservative low-latency defaults; override via environment if needed.
BLOCK_SIZE = max(480, int(os.getenv("BELIZARIUS_BLOCK_SIZE", "960")))  # 20 ms at 48 kHz
PLAYBACK_CHUNK_SAMPLES = max(240, int(os.getenv("BELIZARIUS_PLAYBACK_CHUNK_SAMPLES", "960")))
MIC_QUEUE_BLOCKS = max(2, int(os.getenv("BELIZARIUS_MIC_QUEUE_BLOCKS", "10")))
PLAY_QUEUE_CHUNKS = max(5, int(os.getenv("BELIZARIUS_PLAY_QUEUE_CHUNKS", "25")))
MAX_SESSION_RETRIES = max(0, int(os.getenv("BELIZARIUS_MAX_SESSION_RETRIES", "3")))
RETRY_BASE_SECONDS = max(0.25, float(os.getenv("BELIZARIUS_RETRY_BASE_SECONDS", "1.0")))
METRICS_INTERVAL_SECONDS = max(5.0, float(os.getenv("BELIZARIUS_METRICS_INTERVAL_SECONDS", "15")))

audio_queue = queue.Queue(maxsize=MIC_QUEUE_BLOCKS)
running = True
callback_count = 0
last_metrics_log = 0.0
playback_generation = [0]          # Mutable counter shared with playback coroutine.
active_speaker = [None]            # Current output stream, shared with interruption handler.
speaker_lock = threading.Lock()


def log(message):
    print(message, flush=True)


def clear_audio_queue(q):
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


def stop_speaker_immediately():
    """Abort queued device audio; serialized against short playback writes."""
    with speaker_lock:
        speaker = active_speaker[0]
        if speaker is None:
            return
        try:
            speaker.abort()
            # PortAudio abort discards buffered output. Restart for later speech.
            speaker.start()
        except Exception as exc:
            log(f"SPEAKER_INTERRUPT_WARNING: {type(exc).__name__}: {exc}")


def write_audio_chunk(speaker, generation, audio_bytes):
    with speaker_lock:
        if not running or generation != playback_generation[0]:
            return
        speaker.write(audio_bytes)


def audio_callback(indata, frames, time_info, status):
    """Real-time callback: no blocking I/O, expensive work, or frequent logging."""
    global callback_count, last_metrics_log
    if status:
        now = time.monotonic()
        if now - last_metrics_log >= METRICS_INTERVAL_SECONDS:
            last_metrics_log = now
            log(f"MIC_STATUS: {status}")
    raw_audio = bytes(indata)
    try:
        audio_queue.put_nowait((time.monotonic(), raw_audio))
    except queue.Full:
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            audio_queue.put_nowait((time.monotonic(), raw_audio))
        except queue.Full:
            pass
    callback_count += 1


async def send_microphone_audio(session, send_lock):
    """Send freshest microphone audio; report queue-to-send latency periodically."""
    sent = 0
    latency_total = 0.0
    while running:
        try:
            captured_at, chunk = await asyncio.to_thread(audio_queue.get, True, 0.5)
        except queue.Empty:
            continue
        samples = np.frombuffer(chunk, dtype=np.int16)
        pcm_16k = await asyncio.to_thread(
            lambda: np.clip(resample_poly(samples, up=1, down=3), -32768, 32767)
            .astype(np.int16).tobytes()
        )
        queued_ms = max(0.0, (time.monotonic() - captured_at) * 1000)
        async with send_lock:
            started = time.monotonic()
            await session.send_realtime_input(
                audio=types.Blob(data=pcm_16k, mime_type="audio/pcm;rate=16000")
            )
        sent += 1
        latency_total += queued_ms
        if sent % 50 == 0:
            log(f"AUDIO_METRICS: mic_queue_to_send_avg_ms={latency_total / sent:.1f}; send_ms={(time.monotonic()-started)*1000:.1f}; mic_chunks={sent}")


def tool_declarations():
    """Build Gemini function declarations for supported actions."""
    string = {"type": "STRING"}
    return [
        types.FunctionDeclaration(
            name="create_file",
            description="Create a UTF-8 text file inside Belizarius_Workspace. Do not overwrite an existing file without asking first.",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING", "description": "Relative path inside Belizarius_Workspace"},
                    "content": {"type": "STRING", "description": "Complete initial file contents"},
                },
                "required": ["name", "content"],
            },
        ),
        types.FunctionDeclaration(
            name="read_file",
            description="Read a UTF-8 text file inside Belizarius_Workspace.",
            parameters={
                "type": "OBJECT",
                "properties": {"name": string},
                "required": ["name"],
            },
        ),
        types.FunctionDeclaration(
            name="write_file",
            description="Replace the contents of an existing UTF-8 text file inside Belizarius_Workspace.",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "name": string,
                    "content": {"type": "STRING", "description": "New complete file contents"},
                },
                "required": ["name", "content"],
            },
        ),
        types.FunctionDeclaration(
            name="open_file",
            description="Open an existing file inside Belizarius_Workspace using its default Windows application.",
            parameters={
                "type": "OBJECT",
                "properties": {"name": string},
                "required": ["name"],
            },
        ),
        types.FunctionDeclaration(
            name="delete_file",
            description="Deletion is currently disabled. Never call this to delete a file; explain that deletion needs a future explicit confirmation UI.",
            parameters={
                "type": "OBJECT",
                "properties": {"name": string},
                "required": ["name"],
            },
        ),
        types.FunctionDeclaration(
            name="open_website",
            description="Open a valid HTTP or HTTPS website in the default browser.",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "url": {"type": "STRING", "description": "Full http:// or https:// URL"}
                },
                "required": ["url"],
            },
        ),
        types.FunctionDeclaration(
            name="play_youtube",
            description="Find the best matching YouTube video for a song, artist, album, or music request and open that video's watch page (not just search results)." ,
            parameters={
                "type": "OBJECT",
                "properties": {
                    "query": {"type": "STRING", "description": "Song, artist, or music to search for"}
                },
                "required": ["query"],
            },
        ),
        types.FunctionDeclaration(
            name="set_volume",
            description="Set the Windows system master volume to a percentage from 0 to 100. Use this whenever the user asks to raise, lower, mute, unmute, or set the volume.",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "level": {"type": "INTEGER", "description": "Desired system volume percentage, from 0 (muted) to 100 (maximum)"}
                },
                "required": ["level"],
            },
        ),
        types.FunctionDeclaration(
            name="get_date_time",
            description="Get the computer's current local date, time, and weekday. Use this for questions about today's date, the current time, or the day of the week instead of guessing.",
            parameters={"type": "OBJECT", "properties": {}},
        ),
        types.FunctionDeclaration(
            name="compose_email",
            description="Open a prefilled email draft in the user's default email handler. Never sends the email. Before calling, if the recipient's email address has not been explicitly provided in the current conversation, ask the user for it and wait. Confirm the recipient, subject, and body before any sending; this tool only opens a draft.",
            parameters={
                "type": "OBJECT",
                "properties": {
                    "recipient_email": {"type": "STRING", "description": "Email address explicitly supplied by the user"},
                    "subject": {"type": "STRING"},
                    "body": {"type": "STRING", "description": "Email body text"},
                },
                "required": ["recipient_email", "subject", "body"],
            },
        ),
    ]


def execute_tool(name, args):
    """Synchronous tool dispatcher; called through asyncio.to_thread."""
    if name == "create_file":
        return os_tools.create_file(**args)
    if name == "read_file":
        return os_tools.read_file(**args)
    if name == "write_file":
        return os_tools.write_file(**args)
    if name == "open_file":
        return os_tools.open_file(**args)
    if name == "delete_file":
        return "Deletion is disabled. No file was deleted."
    if name == "open_website":
        return os_tools.open_website(**args)
    if name == "play_youtube":
        # Resolve a real video ID first, then open its watch page. Keep the existing
        # os_tools integration as a fallback if yt-dlp is not installed or fails.
        query = str(args.get("query", "")).strip()
        if not query:
            return "No YouTube search query was provided."
        try:
            result = subprocess.run(
                [sys.executable, "-m", "yt_dlp", "--no-warnings", "--flat-playlist",
                 "--playlist-end", "1", "--print", "id", f"ytsearch1:{query}"],
                capture_output=True, text=True, timeout=25, check=False,
            )
            video_id = next(
                (line.strip() for line in result.stdout.splitlines()
                 if len(line.strip()) == 11 and all(ch.isalnum() or ch in "_-" for ch in line.strip())),
                None,
            )
            if result.returncode == 0 and video_id:
                video_url = f"https://www.youtube.com/watch?v={video_id}&autoplay=1"
                opened = os_tools.open_website(url=video_url)
                return f"Opened the YouTube video page: {video_url}. Browser autoplay may depend on browser settings. {opened}"
        except (subprocess.TimeoutExpired, OSError, Exception) as exc:
            log(f"YOUTUBE_RESOLUTION_FALLBACK: {type(exc).__name__}: {exc}")
        return os_tools.play_youtube(query=query)
    if name == "set_volume":
        level = int(args.get("level", -1))
        if not 0 <= level <= 100:
            return "Volume was not changed: level must be between 0 and 100."
        try:
            from pycaw.pycaw import AudioUtilities
            speakers = AudioUtilities.GetSpeakers()
            volume = speakers.EndpointVolume
            volume.SetMasterVolumeLevelScalar(level / 100.0, None)
            return f"Windows master volume set to {level}%."
        except ImportError:
            return "Could not change volume because pycaw is not installed. Install it with: python -m pip install pycaw comtypes"
        except Exception as exc:
            return f"Could not change Windows master volume: {type(exc).__name__}: {exc}"
    if name == "get_date_time":
        now = datetime.now().astimezone()
        return now.strftime("Computer local date: %A, %B %d, %Y. Local time: %I:%M:%S %p %Z (UTC offset %z).")
    if name == "compose_email":
        return os_tools.compose_email(**args)
    return f"Unknown tool: {name}"


async def handle_tool_call(session, tool_call, send_lock):
    """Execute calls concurrently, then return their results to Gemini."""
    calls = list(tool_call.function_calls or [])
    if not calls:
        return

    async def run_one(call):
        args = dict(call.args or {})
        try:
            result = await asyncio.to_thread(execute_tool, call.name, args)
            log(f"TOOL_RESULT: {call.name}: {result}")
        except Exception as exc:
            result = f"Tool failed: {type(exc).__name__}: {exc}"
            log(f"ERROR: {call.name}: {result}")
            traceback.print_exc()

        return types.FunctionResponse(
            id=call.id,
            name=call.name,
            response={"result": str(result)},
        )

    responses = await asyncio.gather(*(run_one(call) for call in calls))

    # Critical: without this, Gemini never receives the tool results and may stay silent.
    try:
        async with send_lock:
            await session.send_tool_response(function_responses=responses)
        log(f"TOOL_RESPONSES_SENT: {len(responses)}")
    except Exception as exc:
        log(f"TOOL_RESPONSE_SEND_ERROR: {type(exc).__name__}: {exc}")


def _prepare_output_chunks(audio_bytes):
    samples = np.frombuffer(audio_bytes, dtype=np.int16)
    if samples.size == 0:
        return []
    samples_48k = np.clip(resample_poly(samples, up=2, down=1), -32768, 32767).astype(np.int16)
    return [
        samples_48k[start:start + PLAYBACK_CHUNK_SAMPLES].tobytes()
        for start in range(0, len(samples_48k), PLAYBACK_CHUNK_SAMPLES)
    ]


async def enqueue_audio(play_queue, generation, audio_bytes):
    # Resampling is CPU work; do not run it on the event loop.
    # IMPORTANT: never drop arbitrary playback chunks to make room. Doing so
    # causes audible skipped syllables/phrases even when the transcript is complete.
    chunks = await asyncio.to_thread(_prepare_output_chunks, audio_bytes)
    for piece in chunks:
        while running and generation == playback_generation[0]:
            try:
                await asyncio.wait_for(
                    play_queue.put((generation, piece)),
                    timeout=0.1,
                )
                break
            except asyncio.TimeoutError:
                # Backpressure is intentional: preserve speech order. If an
                # interruption changes the generation, abandon the stale chunk.
                continue
        else:
            return


async def playback_worker(play_queue):
    """Keep one output stream open and reject stale-generation chunks."""
    with sd.RawOutputStream(
        samplerate=OUTPUT_RATE, channels=1, dtype="int16",
        blocksize=PLAYBACK_CHUNK_SAMPLES,
    ) as speaker:
        active_speaker[0] = speaker
        log("SPEAKER_READY")
        try:
            while running:
                try:
                    generation, audio_bytes = await asyncio.wait_for(play_queue.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                if generation != playback_generation[0]:
                    continue
                await asyncio.to_thread(write_audio_chunk, speaker, generation, audio_bytes)
        finally:
            active_speaker[0] = None


async def receive_gemini_audio(session, play_queue, send_lock):
    """Receive one session. Connection errors escape to the bounded supervisor."""
    tool_tasks = set()
    try:
        async for response in session.receive():
            if not running:
                break
            tool_call = getattr(response, "tool_call", None)
            if tool_call:
                task = asyncio.create_task(handle_tool_call(session, tool_call, send_lock))
                tool_tasks.add(task)
                task.add_done_callback(tool_tasks.discard)

            content = getattr(response, "server_content", None)
            if content is None:
                continue

            if getattr(content, "interrupted", False):
                playback_generation[0] += 1
                clear_audio_queue(play_queue)
                await asyncio.to_thread(stop_speaker_immediately)
                log("INTERRUPTED: playback flushed; live session retained.")

            input_transcription = getattr(content, "input_transcription", None)
            if input_transcription and getattr(input_transcription, "text", None):
                log(f"YOU SAID: {input_transcription.text}")
            output_transcription = getattr(content, "output_transcription", None)
            if output_transcription and getattr(output_transcription, "text", None):
                log(f"BELIZARIUS: {output_transcription.text}")

            model_turn = getattr(content, "model_turn", None)
            if model_turn:
                generation = playback_generation[0]
                for part in model_turn.parts:
                    inline_data = getattr(part, "inline_data", None)
                    if inline_data and getattr(inline_data, "data", None):
                        await enqueue_audio(play_queue, generation, inline_data.data)

            if getattr(content, "turn_complete", False):
                log("TURN_COMPLETE: listening session remains active")
    finally:
        if tool_tasks:
            await asyncio.gather(*list(tool_tasks), return_exceptions=True)


async def main():
    global running, callback_count
    running = True
    callback_count = 0
    playback_generation[0] = 0
    clear_audio_queue(audio_queue)

    if not API_KEY or API_KEY == "PASTE_YOUR_API_KEY_HERE":
        log("ERROR: GEMINI_API_KEY is missing from the project root .env file.")
        return

    client = genai.Client(api_key=API_KEY)
    play_queue = asyncio.Queue(maxsize=PLAY_QUEUE_CHUNKS)
    send_lock = asyncio.Lock()

    config = {
        "response_modalities": ["AUDIO"],
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "tools": [types.Tool(function_declarations=tool_declarations())],
        "speech_config": {
            "voice_config": {
                "prebuilt_voice_config": {"voice_name": "Algenib"}
            }
        },
        "system_instruction": (
            "You are Belizarius, a battle-hardened Roman soldier and commander, "
            "with a confident, warm, commanding voice and a subtle Latin-influenced accent. "
            "You are a conversational desktop companion, not a one-shot command processor. "
            "Keep the conversation open and respond naturally to each user turn. A completed "
            "answer is not the end of the session. If you ask a clarification question, "
            "treat the user's next utterance as the answer to that question and continue "
            "the pending task rather than starting over. "
            "After every tool operation, always speak a concise confirmation of the actual "
            "tool result; never finish a successful task silently and never claim success "
            "unless the tool result confirms it. If a tool fails, explain the failure plainly. "
            "You may handle independent requested actions concurrently by making multiple tool "
            "calls when appropriate, and you should keep responding to new user speech while "
            "tasks are running. Briefly announce progress for lengthy work. "
            "When the user starts speaking while you are speaking, this is a conversational "
            "barge-in, not a command to end the session or return to wake-word mode. The audio "
            "playback layer will stop your speech; keep listening in this same live session. "
            "Intelligently classify the utterance using the full conversation context: if it is "
            "a correction, answer, clarification, added constraint, or follow-up, continue the "
            "current task with that context; if it is clearly a different request, handle it as "
            "a new task while preserving the conversation history. If ambiguous, ask one short "
            "clarifying question. Do not assume every interruption is a new task. Do not cancel "
            "an already-started file operation merely because speech was interrupted. For file "
            "creation, writing, and reading, use the supplied tools. "
            "Only access files through those tools. Deletion is disabled; do not attempt it. "
            "For system volume requests, always use set_volume with the requested percentage; "
            "for requests to mute, use level 0, and for unmute use a sensible nonzero level "
            "such as 30 if no previous level is available. Never claim volume changed unless "
            "the tool confirms it. For today's date, current time, or weekday, always call "
            "get_date_time rather than guessing. "
            "For website requests, use open_website. For music requests, use play_youtube to "
            "open the best matching YouTube video's watch page. Be honest if resolution fails "
            "or browser autoplay is blocked. "
            "When asked to write an email to a person and their email address is not known in "
            "the current conversation, ask for that address and wait before preparing the draft. "
            "The email tool only opens a draft; it never sends email. Be clear that the user "
            "must review and send it themselves. Ask a brief clarification when required, but "
            "do not ask unnecessary questions."
        ),
    }

    playback_task = None
    consecutive_failures = 0
    try:
        # Keep microphone and speaker streams alive across recoverable session failures.
        with sd.RawInputStream(
            samplerate=DEVICE_RATE, blocksize=BLOCK_SIZE, device=DEVICE_ID,
            dtype="int16", channels=1, callback=audio_callback,
        ):
            log("MICROPHONE_READY: Speak now.")
            log("CONVERSATION_READY: Belizarius will remain listening.")
            playback_task = asyncio.create_task(playback_worker(play_queue), name="belizarius-playback")

            while running:
                session_tasks = set()
                session_started = time.monotonic()
                try:
                    log("CONNECTING_TO_GEMINI")
                    async with client.aio.live.connect(model=MODEL, config=config) as session:
                        log("GEMINI_CONNECTED")
                        clear_audio_queue(audio_queue)
                        sender = asyncio.create_task(send_microphone_audio(session, send_lock), name="belizarius-mic-sender")
                        receiver = asyncio.create_task(receive_gemini_audio(session, play_queue, send_lock), name="belizarius-gemini-receiver")
                        session_tasks = {sender, receiver}
                        monitored_tasks = set(session_tasks) | {playback_task}
                        done, pending = await asyncio.wait(
                            monitored_tasks, return_when=asyncio.FIRST_COMPLETED
                        )
                        if playback_task in done:
                            error = playback_task.exception() if not playback_task.cancelled() else None
                            raise RuntimeError(f"Playback worker stopped unexpectedly: {error or 'cancelled'}")
                        for task in done:
                            if task.cancelled():
                                continue
                            error = task.exception()
                            if error:
                                raise error
                        if running:
                            raise ConnectionError("Gemini Live session ended unexpectedly")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if time.monotonic() - session_started >= 30:
                        consecutive_failures = 0
                    consecutive_failures += 1
                    log(f"GEMINI_SESSION_ERROR: {type(exc).__name__}: {exc}")
                    if consecutive_failures > MAX_SESSION_RETRIES:
                        log("GEMINI_RECONNECT_LIMIT_REACHED: stopping conversation engine.")
                        break
                    delay = min(15.0, RETRY_BASE_SECONDS * (2 ** (consecutive_failures - 1)))
                    log(f"GEMINI_RECONNECT: attempt={consecutive_failures}/{MAX_SESSION_RETRIES}; delay_s={delay:.1f}")
                    await asyncio.sleep(delay)
                finally:
                    for task in session_tasks:
                        if not task.done():
                            task.cancel()
                    if session_tasks:
                        await asyncio.gather(*session_tasks, return_exceptions=True)

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log(f"ERROR: {type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        running = False
        if playback_task and not playback_task.done():
            playback_task.cancel()
            await asyncio.gather(playback_task, return_exceptions=True)
        clear_audio_queue(audio_queue)
        clear_audio_queue(play_queue)
        try:
            client.close()
        except Exception:
            pass
        log("CONVERSATION_STOPPED")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        running = False
        print("\nStopped.", flush=True)
