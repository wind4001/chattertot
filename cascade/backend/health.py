"""本机只读就绪检查；不请求云端、不生成语音、不返回凭据。"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import httpx

import db
import llm
import tts


def project_id():
    root = os.path.normcase(str(Path(__file__).resolve().parents[2]))
    return hashlib.sha256(root.encode()).hexdigest()[:16]


def live_report():
    return {"service": "chattertot", "project_id": project_id(),
            "mode": os.getenv("CHATTERTOT_RUN_MODE", "production"), "status": "alive"}


def result(name, ok, message, action=""):
    return {"name": name, "ok": ok, "message": message, "action": action if not ok else ""}


def check_configuration(values=None):
    if values is None:
        values = {"LLM_API_KEY": llm.LLM_API_KEY, "TTS_API_KEY": tts.TTS_API_KEY,
                  "LLM_BASE_URL": llm.LLM_BASE_URL, "LLM_MODEL": llm.LLM_MODEL, "DB_URL": db.DB_URL}
    checks = []
    placeholders = {"xxx", "changeme", "change_me", "your_api_key", "your-key", "replace_me", "sk-xxx"}
    for name in ("LLM_API_KEY", "TTS_API_KEY"):
        value = str(values.get(name, "")).strip()
        valid = bool(value) and value.lower() not in placeholders and not value.startswith(("<", "${"))
        checks.append(result(name, valid, "已配置（未联网验证有效性）" if valid else "未填写或仍是占位符",
                             f"在 cascade/backend/.env 填写 {name}，然后重新启动"))
    for name, schemes in (("LLM_BASE_URL", ("http", "https")), ("DB_URL", ("postgresql", "postgres"))):
        try:
            parsed = urlsplit(str(values.get(name, "")))
            valid = parsed.scheme in schemes and bool(parsed.hostname)
            if name == "DB_URL":
                valid = valid and bool(parsed.path.strip("/"))
        except ValueError:
            valid = False
        checks.append(result(name, valid, "地址格式正确" if valid else "地址格式不正确",
                             f"检查 cascade/backend/.env 中的 {name}"))
    valid = bool(str(values.get("LLM_MODEL", "")).strip())
    checks.append(result("LLM_MODEL", valid, "已配置" if valid else "模型名为空", "填写 LLM_MODEL"))
    return checks


async def check_database():
    connection = None
    try:
        connection = await asyncpg.connect(db.DB_URL, timeout=3, command_timeout=3)
        await connection.fetch("SELECT id, role, content FROM messages LIMIT 0")
        await connection.fetch("SELECT scope, facts, last_message_id FROM profile LIMIT 0")
        return result("database", True, "数据库连接及对话、记忆表可用")
    except Exception as error:
        if isinstance(error, asyncpg.InvalidPasswordError):
            message = "数据库认证失败"
            action = "核对 .env 的 DB_URL 与已有数据库口令；启动器不会重置已有口令"
        elif isinstance(error, (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError)):
            message = "数据库表或字段缺失"
            action = "运行启动入口补齐缺失表；已有字段不兼容时请检查数据库版本"
        else:
            message = f"数据库不可用（{type(error).__name__}）"
            action = "检查 Docker Desktop、数据库容器和 DB_URL；查看后端日志"
        return result("database", False, message, action)
    finally:
        if connection is not None:
            await connection.close(timeout=2)


async def check_model(client, name, url, route):
    try:
        response = await client.get(url)
        response.raise_for_status()
        if route not in response.json().get("paths", {}):
            raise ValueError("Unexpected service")
        return result(name, True, "模型接口已就绪")
    except Exception as error:
        return result(name, False, f"模型接口未就绪（{type(error).__name__}）",
                      "运行启动入口；仍失败时查看 docker compose -p cascade -f cascade/docker-compose.yml logs --tail 80 asr，检查端口和模型缓存")


async def check_readiness(config_only=False):
    checks = check_configuration()
    if not config_only:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            checks.extend(await asyncio.gather(
                check_database(),
                check_model(client, "asr", "http://127.0.0.1:8000/openapi.json", "/v1/audio/transcriptions"),
                check_model(client, "speaker", "http://127.0.0.1:8001/openapi.json", "/embedding"),
                check_model(client, "kws", "http://127.0.0.1:8002/openapi.json", "/detect"),
            ))
    report = live_report()
    report.update(status="ready" if all(item["ok"] for item in checks) else "not_ready", checks=checks)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(check_readiness(args.config_only))
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        for check in report["checks"]:
            print(f"[{'OK' if check['ok'] else 'FAIL'}] {check['name']}: {check['message']}")
            if check["action"]:
                print("  建议：" + check["action"])
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
