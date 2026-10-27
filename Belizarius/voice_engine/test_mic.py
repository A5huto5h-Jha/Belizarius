import sounddevice as sd
import numpy as np

for device in [15, 14]:
    info = sd.query_devices(device)
    rate = int(info["default_samplerate"])
    print(f"\nTesting device {device}: {info['name']} at {rate} Hz")

    try:
        with sd.RawInputStream(
            device=device,
            samplerate=rate,
            channels=1,
            dtype="int16",
            blocksize=rate // 10
        ) as stream:
            print("Speak for 4 seconds...")
            for i in range(40):
                data, overflow = stream.read(rate // 10)
                if i % 10 == 0:
                    audio = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    rms = float(np.sqrt(np.mean(audio ** 2)))
                    print(f"RMS: {rms:.1f}, overflow: {overflow}")
    except Exception as e:
        print("FAILED:", e)
