#!/bin/bash
# 同时跑 ASR（8000）、声纹（8001）、唤醒词（8002）。任一服务退出则重启整组。
set -euo pipefail
pids=()
cleanup() {
    kill "${pids[@]}" 2>/dev/null || true
    wait "${pids[@]}" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

# 后台启动 ASR 服务（用本地模型路径，避免联网 tcp 409）
funasr-server --model-path /models/models/iic--SenseVoiceSmall/snapshots/master --host 0.0.0.0 --port 8000 --device cpu &
pids+=("$!")

# 后台启动声纹服务
python /app/speaker_api.py &
pids+=("$!")

# 后台启动 KWS 唤醒词服务
python /app/kws_api.py &
pids+=("$!")

# 不能用裸 wait：它会隐藏单个服务的启动失败，让容器一直显示运行中。
wait -n "${pids[@]}"
exit 1
