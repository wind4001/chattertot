"""阶段0 benchmark：SenseVoice vs Zipformer 流式，真实音频精度对比。

SenseVoice（非流式，funasr 8000）对比 Zipformer streaming（sherpa-onnx）。
Zipformer 侧做 AGC 归一化（RMS 归一化到目标值），模拟前端自动增益。
"""
import io
import json
import os
import urllib.request
import wave
import numpy as np
import sherpa_onnx

# 路径基于本文件位置推导，不写死绝对路径（换机器/换盘符也能跑）
_CASCADE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD = os.path.join(_CASCADE, "models", "sherpa-zipformer-bilingual-zh-en")
AD = os.path.join(_CASCADE, "backend", "debug_audio")
SV_URL = "http://localhost:8000/v1/audio/transcriptions"

TARGET_RMS = 3000  # 归一化目标 RMS（int16 尺度），约 -20.8 dBFS

TEST = [
    "turn_1790437498611.wav",
    "turn_1790437650888.wav",
    "turn_1790437778620.wav",
    "turn_1790439217886.wav",
    "turn_1790439235411.wav",
    "turn_1790489661909.wav",
]


def sensevoice(wav_bytes):
    req = urllib.request.Request(
        SV_URL, data=wav_bytes, method="POST",
        headers={"Content-Type": "audio/wav"},
    )
    # 用 multipart 较麻烦，改用 curl 风格：直接 POST 二进制 + query 参数
    return ""


def load_wav(path):
    with wave.open(path, "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        pcm = wf.readframes(n)
    return sr, np.frombuffer(pcm, dtype=np.int16)


def zipformer_rec(recognizer, samples, sr):
    st = recognizer.create_stream()
    chunk = int(sr * 0.1)
    for i in range(0, len(samples), chunk):
        st.accept_waveform(sr, samples[i : i + chunk])
        while recognizer.is_ready(st):
            recognizer.decode_stream(st)
    st.input_finished()
    while recognizer.is_ready(st):
        recognizer.decode_stream(st)
    return recognizer.get_result(st)


def main():
    rec = sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=f"{MD}/tokens.txt", encoder=f"{MD}/encoder-epoch-99-avg-1.int8.onnx",
        decoder=f"{MD}/decoder-epoch-99-avg-1.int8.onnx", joiner=f"{MD}/joiner-epoch-99-avg-1.int8.onnx",
        num_threads=4, sample_rate=16000, feature_dim=80, decoding_method="greedy_search",
        enable_endpoint_detection=False,
    )

    print(f"{'音频':28s} | {'SenseVoice(原始)':22s} | {'Zipformer(AGC)':22s}")
    print("-" * 80)

    for name in TEST:
        path = f"{AD}/{name}"
        sr, pcm = load_wav(path)

        # SenseVoice：调 funasr 8000（用 curl 命令更简单，这里用 urllib multipart）
        # 简化：用 subprocess 调 curl
        import subprocess
        r = subprocess.run(
            ["curl", "-s", "--max-time", "60", "-X", "POST", SV_URL,
             "-F", f"file=@{path}", "-F", "model=sensevoice"],
            capture_output=True, text=True, encoding="utf-8",
        )
        try:
            sv_text = json.loads(r.stdout).get("text", "")
        except Exception:
            sv_text = f"(解析失败:{r.stdout[:50]})"

        # Zipformer：AGC 归一化
        rms = np.sqrt(np.mean(pcm.astype(np.float64) ** 2))
        gain = TARGET_RMS / rms if rms > 0 else 1.0
        samples = np.clip(pcm.astype(np.float32) * gain / 32768.0, -1.0, 1.0)
        zf_text = zipformer_rec(rec, samples, sr)

        print(f"{name:28s} | {sv_text:22s} | {zf_text:22s}")


if __name__ == "__main__":
    main()
