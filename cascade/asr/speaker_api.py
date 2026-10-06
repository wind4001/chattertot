"""CAM++ 声纹提取服务：WAV 音频 -> 192 维声纹向量。"""
import numpy as np
from fastapi import FastAPI, File, UploadFile
from funasr import AutoModel

app = FastAPI(title="Speaker Embedding")

model = AutoModel(
    model="/models/models/iic--speech_campplus_sv_zh-cn_16k-common/snapshots/master",
    device="cpu",
    disable_update=True,
)


@app.post("/embedding")
async def embedding(file: UploadFile = File(...)):
    data = await file.read()
    path = "/tmp/spk_input.wav"
    with open(path, "wb") as f:
        f.write(data)
    r = model.generate(input=path)
    emb = r[0]["spk_embedding"].detach().cpu().numpy().flatten()
    return {"embedding": emb.tolist()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
