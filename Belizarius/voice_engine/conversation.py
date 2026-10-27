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
BLOCK_SIZE = 4800                 # 100 ms at 48 kHz
PLAYBACK_CHUNK_SAMPLES = 960      # 20 ms at 48 kHz

audio_queue = queue.Queue(maxsize=30)
running = True
callback_count = 0
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
    """Flush the device's buffered speech without closing the conversation/mic."""
    with speaker_lock:
        speaker = active_speaker[0]
        if speaker is None:
            return
        try:
            # abort() discards audio already buffered by PortAudio; restart the same
            # stream so later Gemini speech can still be played.
            speaker.abort()
            speaker.start()
        except Exception as exc:
            log(f"SPEAKER_INTERRUPT_WARNING: {type(exc).__name__}: {exc}")


def write_audio_chunk(speaker, generation, audio_bytes):
    """Serialize speaker writes with interruption flushes."""
    with speaker_lock:
        if not running or generation != playback_generation[0]:
            return
        speaker.write(audio_bytes)


def audio_callback(indata, frames, time_info, status):
    """PortAudio callback: keep it short and never block on a full queue."""
    global callback_count

    if status:
        log(f"MIC_STATUS: {status}")

    raw_audio = bytes(indata)
    try:
        audio_queue.put_nowait(raw_audio)
    except queue.Full:
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            audio_queue.put_nowait(raw_audio)
        except queue.Full:
            pass

    callback_count += 1
    if callback_count % 10 == 0:
        samples = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32)
        if samples.size:
            rms = float(np.sqrt(np.mean(samples ** 2)))
            log(f"MIC_LEVEL: {rms:.0f}")


async def send_microphone_audio(session, send_lock):
    """Continuously stream microphone PCM to Gemini until the session stops."""
    while running:
        try:
            chunk = await asyncio.to_thread(audio_queue.get, True, 0.5)
        except queue.Empty:
            continue

        samples = np.frombuffer(chunk, dtype=np.int16)
        samples_16k = resample_poly(samples, up=1, down=3)
        pcm_16k = np.clip(samples_16k, -32768, 32767).astype(np.int16).tobytes()

        # Serialize WebSocket sends so audio chunks and tool responses do not race.
        async with send_lock:
            await session.send_realtime_input(
                audio=types.Blob(
                    data=pcm_16k,
                    mime_type="audio/pcm;rate=16000",
                )
            )


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


def enqueue_audio(play_queue, generation, audio_bytes):
    """Split output into small pieces so interruption latency stays low."""
    samples = np.frombuffer(audio_bytes, dtype=np.int16)
    if samples.size == 0:
        return

    # Gemini Live generated audio is typically 24 kHz PCM; upsample to 48 kHz.
    samples_48k = resample_poly(samples, up=2, down=1)
    samples_48k = np.clip(samples_48k, -32768, 32767).astype(np.int16)

    for start in range(0, len(samples_48k), PLAYBACK_CHUNK_SAMPLES):
        piece = samples_48k[start:start + PLAYBACK_CHUNK_SAMPLES].tobytes()
        item = (generation, piece)
        try:
            play_queue.put_nowait(item)
        except asyncio.QueueFull:
            # Keep recent audio rather than accumulating a long, stale response.
            try:
                play_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                play_queue.put_nowait(item)
            except asyncio.QueueFull:
                pass


async def playback_worker(play_queue):
    """Play chunks while remaining interruptible; interruption flushes device audio."""
    with sd.RawOutputStream(
        samplerate=OUTPUT_RATE,
        channels=1,
        dtype="int16",
        blocksize=PLAYBACK_CHUNK_SAMPLES,
    ) as speaker:
        active_speaker[0] = speaker
        log("SPEAKER_READY")
        try:
            while running:
                try:
                    generation, audio_bytes = await asyncio.wait_for(
                        play_queue.get(), timeout=0.25
                    )
                except asyncio.TimeoutError:
                    continue

                if generation != playback_generation[0]:
                    continue

                await asyncio.to_thread(
                    write_audio_chunk, speaker, generation, audio_bytes
                )
        finally:
            active_speaker[0] = None


async def receive_gemini_audio(session, play_queue, send_lock):
    """Receive successive turns; interruptions only stop speech, never reset wake word."""
    tool_tasks = set()

    try:
        while running:
            try:
                async for response in session.receive():
                    if not running:
                        break

                    tool_call = getattr(response, "tool_call", None)
                    if tool_call:
                        task = asyncio.create_task(
                            handle_tool_call(session, tool_call, send_lock)
                        )
                        tool_tasks.add(task)
                        task.add_done_callback(tool_tasks.discard)

                    content = getattr(response, "server_content", None)
                    if content is None:
                        continue

                    if getattr(content, "interrupted", False):
                        # This is a barge-in, not a request to end the session. Keep the
                        # same Gemini Live session and its conversation context.
                        playback_generation[0] += 1
                        clear_audio_queue(play_queue)
                        await asyncio.to_thread(stop_speaker_immediately)
                        log("INTERRUPTED: speech stopped; conversation context retained.")

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
                                enqueue_audio(
                                    play_queue,
                                    playback_generation[0],
                                    part.inline_data.data,
                                )

                    if content.turn_complete:
                        log("TURN_COMPLETE: session stays open and keeps listening")

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Don't drop back to wake-word mode because one receive iteration failed.
                # Retry receiving on the current session; if the socket is irrecoverably
                # closed, the retry message makes the actual connection issue visible.
                log(f"GEMINI_RECEIVE_RETRY: {type(exc).__name__}: {exc}")
                await asyncio.sleep(0.75)

            # Some SDK versions end the receive iterator at a turn boundary. Re-enter it.
            if running:
                await asyncio.sleep(0.03)
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
    play_queue = asyncio.Queue(maxsize=250)
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

    try:
        log("CONNECTING_TO_GEMINI")
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            log("GEMINI_CONNECTED")

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
                log("CONVERSATION_READY: Belizarius will remain listening.")

                sender = asyncio.create_task(send_microphone_audio(session, send_lock))
                receiver = asyncio.create_task(
                    receive_gemini_audio(session, play_queue, send_lock)
                )
                playback = asyncio.create_task(playback_worker(play_queue))
                tasks = {sender, receiver, playback}

                try:
                    done, pending = await asyncio.wait(
                        tasks, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in done:
                        error = task.exception()
                        if error:
                            raise error
                    if receiver in done:
                        log("GEMINI_RECEIVER_STOPPED")
                finally:
                    running = False
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

    except asyncio.CancelledError:
        raise
    except Exception as error:
        running = False
        log(f"ERROR: {type(error).__name__}: {error}")
        traceback.print_exc()
    finally:
        running = False
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
