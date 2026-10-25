
import json
import queue
import re
from pathlib import Path

import sounddevice as sd
from vosk import Model, KaldiRecognizer


# Paths and microphone settings
MODEL_PATH = (
    Path(__file__).resolve().parent
    / "models"
    / "vosk-model-small-en-us-0.15"
)

DEVICE_ID = 1
SAMPLE_RATE = 16000
BLOCK_SIZE = 8000

audio_queue = queue.Queue()


def audio_callback(indata, frames, time_info, status):
    if status:
        print(f"Audio status: {status}")

    audio_queue.put(bytes(indata))


def normalize(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def main():
    print("Loading Belizarius speech model...")

    if not MODEL_PATH.exists():
        print(f"Model folder not found: {MODEL_PATH}")
        return

    model = Model(str(MODEL_PATH))
    wake_phrases = [
    "hey belizarius",
    "hey belisarius",
    "hey belly zarius",
    "hey bell is areas",
    "hey bill is ideas",   # Exact transcription from your test
    "hey bill his ideas",  # Alternative transcription
    ]
    recognizer = KaldiRecognizer(model, SAMPLE_RATE)

    print("Model loaded successfully.")
    print("Belizarius is listening for: Hey Belizarius")
    print("Speak clearly. Press Ctrl+C to stop.\n")

    try:
        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            device=DEVICE_ID,
            dtype="int16",
            channels=1,
            callback=audio_callback,
        ):
            while True:
                audio_data = audio_queue.get()

                if recognizer.AcceptWaveform(audio_data):
                    result = json.loads(recognizer.Result())
                    spoken_text = normalize(result.get("text", ""))

                    if spoken_text:
                        print(f"Heard: {spoken_text}")

                    # Initial phrase matching; we'll tune it
                    # if Vosk misrecognizes "Belizarius".
                    if any(phrase in spoken_text for phrase in wake_phrases):
                        print("\n*** WAKE WORD DETECTED! ***\n")
                        print("Belizarius activated.")

    except KeyboardInterrupt:
        print("\nBelizarius listener stopped.")

    except Exception as error:
        print(f"\nListener error: {error}")
        print("Check the microphone device ID and Windows permissions.")


if __name__ == "__main__":
    main()
