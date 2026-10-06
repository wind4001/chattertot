#!/bin/bash
# 测试服务器：独立 DB（chattertot_test）+ 独立端口（8081），与生产（chattertot + 8080）隔离。
#
# 会自动准备测试库（建库 + 建表，幂等），所以可以直接重复运行。
# 需要 chattertot-db 容器已在运行：cd .. && docker compose up -d

set -euo pipefail
cd "$(dirname "$0")"

# 容器名自动探测：优先 chattertot-db，其次早期版本的 lym-db（方便迁移用户）
if [ -z "${DB_CONTAINER:-}" ]; then
  for c in chattertot-db lym-db; do
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$c"; then
      DB_CONTAINER="$c"
      break
    fi
  done
fi
DB_CONTAINER="${DB_CONTAINER:-chattertot-db}"
DB_PASSWORD="${POSTGRES_PASSWORD:-chattertot_dev_pw}"
DB_URL="postgresql://postgres:${DB_PASSWORD}@localhost:5432/chattertot_test"

# --- 1. 选解释器：Windows 是 Scripts/，macOS/Linux 是 bin/ ---
if [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  echo "找不到 .venv。先执行：" >&2
  echo "  python -m venv .venv" >&2
  echo "  .venv/Scripts/pip install -r requirements.txt   # macOS/Linux 用 .venv/bin/pip" >&2
  exit 1
fi

# --- 2. 准备测试库（建库 + 建表，幂等）---
if docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  if ! docker exec "$DB_CONTAINER" psql -U postgres -d postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname=chattertot_test" | grep -q 1; then
    echo "创建测试库 chattertot_test ..."
    docker exec "$DB_CONTAINER" createdb -U postgres chattertot_test
  fi
  docker exec -i "$DB_CONTAINER" psql -q -U postgres -d chattertot_test < ../db/init.sql
  echo "测试库就绪（chattertot_test）。"
else
  echo "警告：容器 $DB_CONTAINER 未运行，跳过建库建表。" >&2
  echo "      先执行：cd .. && docker compose up -d" >&2
fi

# --- 3. 启动 ---
echo "启动测试服务器：http://localhost:8081 （库 chattertot_test，与生产隔离）"
DB_URL="$DB_URL" exec "$PY" -m uvicorn app:app --host 0.0.0.0 --port 8081 --ws auto
