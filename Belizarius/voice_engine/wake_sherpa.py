import queue
from pathlib import Path

import numpy as np
import sounddevice as sd
import sherpa_onnx

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "models" / "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"

SAMPLE_RATE = 16000
DEVICE_ID = 1
BLOCK_SIZE = 1600

audio_queue = queue.Queue()


def audio_callback(indata, frames, time_info, status):
    if status:
        print(f"Audio status: {status}")
    audio_queue.put(bytes(indata))


def main():
    print("Loading Belizarius keyword detector...")

    kws = sherpa_onnx.KeywordSpotter(
        tokens=str(MODEL / "tokens.txt"),
        encoder=str(MODEL / "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
        decoder=str(MODEL / "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
        joiner=str(MODEL / "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
        keywords_file=str(MODEL / "belizarius_keywords.txt"),
        keywords_score=1.0,
        keywords_threshold=0.1,
        num_threads=2,
        provider="cpu",
    )

    stream = kws.create_stream()

    print("Loaded. Say: Hey Belizarius")
    print("Press Ctrl+C to stop.\n")

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
                data = audio_queue.get()
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

                stream.accept_waveform(SAMPLE_RATE, samples)

                while kws.is_ready(stream):
                    kws.decode_stream(stream)
                    result = kws.get_result(stream)

                    if result:
                        print(f"WAKE_WORD:{result}", flush=True)
                        kws.reset_stream(stream)

    except KeyboardInterrupt:
        print("\nBelizarius test stopped.")


if __name__ == "__main__":
    main()
