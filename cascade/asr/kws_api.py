"""FunASR SANM KWS 唤醒词检测服务：检测「小云小云」。"""
import io
import wave

import numpy as np
from fastapi import FastAPI, File, UploadFile
from funasr import AutoModel

app = FastAPI(title="KWS Detect")

MODEL_DIR = "/models/models/iic--speech_sanm_kws_phone-xiaoyun-commands-online"
KEYWORD = "小云小云"

model = AutoModel(
    model=MODEL_DIR, keywords=KEYWORD, device="cpu", ncpu=1,
    chunk_size=[4, 8, 4], encoder_chunk_look_back=0,
    decoder_chunk_look_back=0, disable_update=True, trust_remote_code=False,
)


@app.post("/detect")
async def detect(file: UploadFile = File(...)):
    data = await file.read()
    with wave.open(io.BytesIO(data), "rb") as w:
        sr = w.getframerate()
        pcm = w.readframes(w.getnframes())
    speech = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    results = model.generate(
        input=speech, fs=sr, cache={}, chunk_size=[4, 8, 4],
        batch_size=1, is_final=True,
    )
    text = ""
    for item in results:
        text = item.get("text", "")
    detected = text.startswith("detected")
    score = 0.0
    parts = text.split()
    if detected and len(parts) >= 3:
        try:
            score = float(parts[-1])
        except ValueError:
            pass
    return {"keyword": KEYWORD, "detected": detected, "score": score, "text": text}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)
