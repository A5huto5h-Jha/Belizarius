
import queue
from pathlib import Path

import numpy as np
import sounddevice as sd
import sherpa_onnx
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "models" / "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"

SAMPLE_RATE = 16000          # Rate expected by the keyword detector
DEVICE_RATE = 48000          # Native rate supported by the tested microphone
DEVICE_ID = 21               # AMD Audio Device (WASAPI)
BLOCK_SIZE = 4800            # 100 ms at 48 kHz

audio_queue = queue.Queue(maxsize=30)


def audio_callback(indata, frames, time_info, status):
    if status:
        print(f"Audio status: {status}", flush=True)

    try:
        audio_queue.put_nowait(bytes(indata))
    except queue.Full:
        # Drop the oldest block to keep wake detection responsive.
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            pass

        try:
            audio_queue.put_nowait(bytes(indata))
        except queue.Full:
            pass


def main():
    print("Loading Belizarius keyword detector...", flush=True)

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

    print("Loaded. Say: Hey Belizarius", flush=True)
    print("Microphone: AMD Audio Device at 48000 Hz", flush=True)
    print("Press Ctrl+C to stop.\n", flush=True)

    try:
        with sd.RawInputStream(
            samplerate=DEVICE_RATE,
            blocksize=BLOCK_SIZE,
            device=DEVICE_ID,
            dtype="int16",
            channels=1,
            callback=audio_callback,
        ):
            while True:
                data = audio_queue.get()
                samples = (
                    np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    / 32768.0
                )

                # Convert 48 kHz microphone audio to the detector's 16 kHz input.
                samples_16k = resample_poly(samples, up=1, down=3).astype(
                    np.float32
                )

                stream.accept_waveform(SAMPLE_RATE, samples_16k)

                while kws.is_ready(stream):
                    kws.decode_stream(stream)
                    result = kws.get_result(stream)

                    if result:
                        print(f"WAKE_WORD:{result}", flush=True)
                        kws.reset_stream(stream)

    except KeyboardInterrupt:
        print("\nBelizarius test stopped.", flush=True)


if __name__ == "__main__":
    main()
