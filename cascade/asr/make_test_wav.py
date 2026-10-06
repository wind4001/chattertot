"""把 server/captured_audio.pcm（24k float32 真实语音）转成 16k int16 WAV，用于测试 asr 服务。"""
import array
import struct
import wave

SRC = "server/captured_audio.pcm"
DST = "asr/test.wav"
SRC_RATE = 24000
DST_RATE = 16000

data = open(SRC, "rb").read()
n = len(data) // 4
floats = struct.unpack(f"<{n}f", data[: n * 4])

# 线性重采样 24k -> 16k
m = int(n * DST_RATE / SRC_RATE)
out = array.array("h")
for i in range(m):
    pos = i * SRC_RATE / DST_RATE
    i0 = int(pos)
    i1 = min(i0 + 1, n - 1)
    frac = pos - i0
    v = floats[i0] * (1 - frac) + floats[i1] * frac
    out.append(int(max(-1.0, min(1.0, v)) * 32767))

with wave.open(DST, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(DST_RATE)
    w.writeframes(out.tobytes())

print(f"OK: {DST}  {len(out)} samples = {len(out)/DST_RATE:.1f}s")
