"""数据库访问层：PostgreSQL 存对话历史（多轮记忆，全局单流）。"""
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DB_URL", "postgresql://postgres:chattertot_dev_pw@localhost:5432/chattertot")

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=5)
    return _pool


async def add_message(role: str, content: str):
    """追加一条对话消息到全局历史。"""
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO messages (role, content) VALUES ($1, $2)", role, content
    )


async def get_recent_messages(limit: int = 20) -> list:
    """读取全局最近 N 条消息，返回时间正序的 [{"role","content"},...]。"""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT role, content FROM messages ORDER BY id DESC LIMIT $1", limit
    )
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def get_messages_since(last_id: int, limit: int = 300) -> list:
    """取 id 大于 last_id 的消息（时间正序），用于增量摘要长期记忆。"""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id, role, content FROM messages WHERE id > $1 ORDER BY id ASC LIMIT $2",
        last_id, limit,
    )
    return [{"id": r["id"], "role": r["role"], "content": r["content"]} for r in rows]


async def get_profile(scope: str = "default") -> dict:
    """读取长期记忆档案。不存在时返回空档案。"""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT facts, last_message_id FROM profile WHERE scope=$1", scope
    )
    if row is None:
        return {"facts": "", "last_message_id": 0}
    return {"facts": row["facts"] or "", "last_message_id": row["last_message_id"] or 0}


async def update_profile(scope: str, facts: str, last_message_id: int):
    """写入长期记忆档案（按 scope upsert）。"""
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO profile (scope, facts, last_message_id, updated_at)
        VALUES ($1, $2, $3, now())
        ON CONFLICT (scope) DO UPDATE
        SET facts = EXCLUDED.facts,
            last_message_id = EXCLUDED.last_message_id,
            updated_at = now()
        """,
        scope, facts, last_message_id,
    )
