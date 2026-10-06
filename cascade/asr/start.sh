#!/bin/bash
# 同时跑两个服务：ASR（8000）+ 声纹提取（8001），共用同一套 torch/funasr 环境
set -e

# 后台启动 ASR 服务（用本地模型路径，避免联网 tcp 409）
funasr-server --model-path /models/models/iic--SenseVoiceSmall/snapshots/master --host 0.0.0.0 --port 8000 --device cpu &

# 后台启动声纹服务
python /app/speaker_api.py &

# 后台启动 KWS 唤醒词服务
python /app/kws_api.py &

# 等待所有后台进程
wait
