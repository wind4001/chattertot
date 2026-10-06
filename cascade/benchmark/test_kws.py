"""sherpa-onnx KWS 唤醒词测试：配置「小月小月」，测 4 段音频的触发/误报。"""
import os
import sys
import time
import wave

import numpy as np
import sherpa_onnx

# 路径基于本文件位置推导，不写死绝对路径（换机器/换盘符也能跑）
_CASCADE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(
    _CASCADE, "models", "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
)
KEYWORDS = os.path.join(_CASCADE, "audio-test", "keywords_xiaoyue.txt")
AUDIO = os.path.join(_CASCADE, "audio-test")


def main():
    spotter = sherpa_onnx.KeywordSpotter(
        tokens=f"{MODEL}/tokens.txt",
        encoder=f"{MODEL}/encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
        decoder=f"{MODEL}/decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
        joiner=f"{MODEL}/joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
        keywords_file=KEYWORDS,
        num_threads=4,
        max_active_paths=4,
        keywords_threshold=0.25,
        provider="cpu",
    )

    def test(path):
        with wave.open(path, "rb") as w:
            sr = w.getframerate()
            n = w.getnframes()
            pcm = w.readframes(n)
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        t0 = time.perf_counter()
        stream = spotter.create_stream()
        stream.accept_waveform(sr, samples)
        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
        result = spotter.get_result(stream)
        ms = (time.perf_counter() - t0) * 1000
        return result, ms

    print("=== 误报测试（这些音频不含「小月小月」，应不触发）===")
    for f in ["child1", "child2", "parent1", "parent2"]:
        r, ms = test(f"{AUDIO}/{f}.wav")
        flag = "误报!" if r else "OK"
        print(f"  {f:10s} 触发={r!r:20s} 处理耗时 {ms:.0f}ms  [{flag}]")


if __name__ == "__main__":
    main()
