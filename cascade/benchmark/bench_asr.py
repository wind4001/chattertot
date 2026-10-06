"""阶段0 benchmark：sherpa-onnx Zipformer 流式 ASR 延迟实测。

测三样：
1. 首 token 延迟（第一次吐出非空 partial 的时间，实时对话关键指标）
2. 整段处理耗时 + RTF（实时率）
3. 识别文本质量（和实际说的对比）
"""
import os
import time
import wave
import sys
import numpy as np
import sherpa_onnx

# 路径基于本文件位置推导，不写死绝对路径（换机器/换盘符也能跑）
_CASCADE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(_CASCADE, "models", "sherpa-zipformer-bilingual-zh-en")
AUDIO_DIR = os.path.join(_CASCADE, "backend", "debug_audio")

# 测试音频：不同时长
TEST_WAVS = [
    "turn_1790437839148.wav",   # ~2.6s
    "turn_1790437498611.wav",   # ~2.65s
    "turn_1790439217886.wav",   # ~4.2s
    "turn_1790439259524.wav",   # ~4.5s
]

CHUNK_MS = 100  # 流式 chunk 时长（模拟实时送入粒度）


def load_wav(path):
    with wave.open(path, "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        pcm = wf.readframes(n)
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return sr, samples


def bench_one(recognizer, sr, samples, label):
    chunk = int(sr * CHUNK_MS / 1000)
    stream = recognizer.create_stream()

    t0 = time.perf_counter()
    first_token_ms = None
    last_text = ""
    for i in range(0, len(samples), chunk):
        stream.accept_waveform(sr, samples[i : i + chunk])
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        text = recognizer.get_result(stream)
        if text and first_token_ms is None:
            first_token_ms = (time.perf_counter() - t0) * 1000
        last_text = text

    stream.input_finished()
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
    final_text = recognizer.get_result(stream)
    total_ms = (time.perf_counter() - t0) * 1000
    dur_s = len(samples) / sr

    print(f"  {label:8s} 音频{dur_s:.2f}s | 首token {first_token_ms or 0:5.0f}ms | "
          f"整段 {total_ms:6.0f}ms | RTF {total_ms/1000/dur_s:4.2f} | 识别: {final_text}")
    return first_token_ms, total_ms, final_text


def main():
    threads = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    print(f"=== sherpa-onnx Zipformer bilingual-zh-en int8 | num_threads={threads} | chunk={CHUNK_MS}ms ===\n")

    recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=f"{MODEL_DIR}/tokens.txt",
        encoder=f"{MODEL_DIR}/encoder-epoch-99-avg-1.int8.onnx",
        decoder=f"{MODEL_DIR}/decoder-epoch-99-avg-1.int8.onnx",
        joiner=f"{MODEL_DIR}/joiner-epoch-99-avg-1.int8.onnx",
        num_threads=threads,
        sample_rate=16000,
        feature_dim=80,
        decoding_method="greedy_search",
        enable_endpoint_detection=False,
    )

    for name in TEST_WAVS:
        sr, samples = load_wav(f"{AUDIO_DIR}/{name}")
        bench_one(recognizer, sr, samples, name)


if __name__ == "__main__":
    main()
