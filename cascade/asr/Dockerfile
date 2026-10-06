# 从干净基础镜像装最新版 funasr，用内置的 funasr-server（OpenAI 兼容接口）
# 基础镜像走国内镜像（Docker Hub 在国内被墙）
FROM docker.m.daocloud.io/library/python:3.11-slim

WORKDIR /app

# 系统依赖：ffmpeg(音频解码) + libsndfile1(torchaudio 需要)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 && \
    rm -rf /var/lib/apt/lists/*

# 国内网络慢的话，取消下面注释启用清华 pip 镜像
# ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 先装 CPU 版 torch（体积小、快），再装 funasr + web 依赖
RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir funasr fastapi uvicorn python-multipart

COPY speaker_api.py /app/speaker_api.py
COPY kws_api.py /app/kws_api.py
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 8000 8001 8002

# 启动脚本同时跑 ASR(8000) + 声纹(8001)
CMD ["bash", "/app/start.sh"]
