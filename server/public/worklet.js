/**
 * 麦克风采集 AudioWorklet：把 Float32 采样转成 Int16 PCM 并回传主线程。
 * 音频上下文 sampleRate 设为 16000，这里直接按 16kHz 出 PCM。
 */
class PCMWorklet extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input && input.length > 0 && input[0]) {
      const ch = input[0];
      const int16 = new Int16Array(ch.length);
      for (let i = 0; i < ch.length; i++) {
        const s = Math.max(-1, Math.min(1, ch[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      // 转移所有权，避免拷贝
      this.port.postMessage(int16.buffer, [int16.buffer]);
    }
    return true;
  }
}

registerProcessor("pcm-worklet", PCMWorklet);
