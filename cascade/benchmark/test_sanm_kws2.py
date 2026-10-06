"""FunASR SANM KWS 对比测试：小云/小月 关键词 × 小云/小月 音频。"""
from funasr import AutoModel
import soundfile as sf

MODEL_DIR = "/models/models/iic--speech_sanm_kws_phone-xiaoyun-commands-online"


def make_model(keywords):
    return AutoModel(
        model=MODEL_DIR, keywords=keywords, device="cpu", ncpu=1,
        chunk_size=[4, 8, 4], encoder_chunk_look_back=0,
        decoder_chunk_look_back=0, disable_update=True, trust_remote_code=False,
    )


def test(model, audio):
    speech, sr = sf.read(audio, dtype="float32")
    results = model.generate(
        input=speech, fs=sr, cache={}, chunk_size=[4, 8, 4],
        batch_size=1, is_final=True,
    )
    for item in results:
        return item.get("text")
    return "(空)"


print("=== 加载 小云 模型 ===", flush=True)
m_xy = make_model("小云小云")
print("=== 加载 小月 模型 ===", flush=True)
m_xue = make_model("小月小月")

print()
print("小云模型 × 小云音频:", test(m_xy, "/tmp/xiaoyun.wav"), flush=True)
print("小云模型 × 小月音频:", test(m_xy, "/tmp/xiaoyue2.wav"), flush=True)
print("小月模型 × 小云音频:", test(m_xue, "/tmp/xiaoyun.wav"), flush=True)
print("小月模型 × 小月音频:", test(m_xue, "/tmp/xiaoyue2.wav"), flush=True)
