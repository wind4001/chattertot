"""FunASR SANM KWS 测试：加载模型，检测关键词「小月小月」。"""
import sys

from funasr import AutoModel
import soundfile as sf

MODEL_DIR = "/models/models/iic--speech_sanm_kws_phone-xiaoyun-commands-online"


def main():
    audio = sys.argv[1] if len(sys.argv) > 1 else "/tmp/xiaoyue_pure.wav"

    print("加载 KWS 模型...", flush=True)
    model = AutoModel(
        model=MODEL_DIR, keywords="小月小月", device="cpu", ncpu=1,
        chunk_size=[4, 8, 4], encoder_chunk_look_back=0,
        decoder_chunk_look_back=0, disable_update=True, trust_remote_code=False,
    )
    print("模型加载完成", flush=True)

    speech, sr = sf.read(audio, dtype="float32")
    print(f"音频 {sr}Hz {len(speech)} samples ({len(speech)/sr:.2f}s)", flush=True)

    results = model.generate(
        input=speech, fs=sr, cache={}, chunk_size=[4, 8, 4],
        batch_size=1, is_final=True,
    )
    for item in results:
        print("结果:", item.get("text"), flush=True)


if __name__ == "__main__":
    main()
