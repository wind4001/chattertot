#!/bin/bash
# 预下载本地推理模型到 asr_models 卷。
#
# 为什么需要这个脚本：start.sh 里三个服务都指向卷内的本地路径（硬编码），
# 因为 funasr-server 用 --model 时会在启动阶段走 ModelScope 的 TCP 加速通道，
# 在国内网络被 409 拒绝而崩溃。所以模型必须预先放好，不能靠服务自己拉。
#
# 实测（2026-10-03，modelscope 1.40.1）：snapshot_download(model_id) 在
# MODELSCOPE_CACHE=/models 时解析到的路径与代码里的硬编码路径完全一致：
#   iic/<name>  ->  /models/models/iic--<name>/snapshots/master
#
# 幂等：已缓存的模型只做校验，不会重复下载。

set -euo pipefail

# Git Bash / MSYS2 会把 `-e MODELSCOPE_CACHE=/models` 里的 /models 当成 Unix 路径
# 自动转换成 Windows 路径（如 G:/ruanjiananzhuang/Git/models），容器里拿到的是个
# 废路径，模型会下到容器内的临时目录并随 --rm 一起消失——**而且不报错**。
# 这个坑之前踩过（卷里残留的 G:--ruanjiananzhuang--Git--... 目录就是证据）。
# MSYS_NO_PATHCONV=1 关掉该转换；Linux/macOS 上设了也无害。
export MSYS_NO_PATHCONV=1

cd "$(dirname "$0")"

IMAGE="${ASR_IMAGE:-cascade-asr:latest}"
VOLUME="${ASR_VOLUME:-cascade_asr_models}"
COMPOSE_FILE="../docker-compose.yml"

MODELS=(
  "iic/SenseVoiceSmall"
  "iic/speech_sanm_kws_phone-xiaoyun-commands-online"
  "iic/speech_campplus_sv_zh-cn_16k-common"
)

# 镜像不存在则先构建（下载要在镜像里跑，因为要用它自带的 modelscope）
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "镜像 $IMAGE 不存在，先构建……"
  docker compose -f "$COMPOSE_FILE" build asr
fi

echo "目标卷：$VOLUME"
echo "待下载：${#MODELS[@]} 个模型"
echo

docker run --rm \
  -v "${VOLUME}:/models" \
  -e MODELSCOPE_CACHE=/models \
  "$IMAGE" \
  python -c '
import sys
from modelscope import snapshot_download

EXPECTED_PREFIX = "/models/models/"
failed = []
for m in sys.argv[1:]:
    try:
        path = snapshot_download(m)
    except Exception as e:
        print(f"  FAIL  {m}: {type(e).__name__}: {e}", flush=True)
        failed.append(m)
        continue
    # 断言：下载必须落在挂载卷里。若不在此前缀下（例如 MSYS 把路径转换坏了），
    # 模型会下到容器临时目录并随 --rm 消失——绝不能让它打印 OK 蒙混过去。
    if not path.startswith(EXPECTED_PREFIX):
        print(f"  FAIL  {m}: 落点 {path} 不在 {EXPECTED_PREFIX} 下（MSYS 路径转换？）", flush=True)
        failed.append(m)
        continue
    print(f"  OK    {m} -> {path}", flush=True)

if failed:
    print(f"\n{len(failed)} 个模型未正确落盘，脚本失败。", flush=True)
sys.exit(1 if failed else 0)
' "${MODELS[@]}"

echo
echo "完成。可用 docker exec chattertot-asr ls /models/models 核对。"
