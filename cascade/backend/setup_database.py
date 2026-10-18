"""Create missing schema in the configured, existing database; preserve stored data."""
import asyncio
from pathlib import Path

import asyncpg
import db


async def initialize_database(url=None):
    connection = await asyncpg.connect(url or db.DB_URL, timeout=5, command_timeout=30)
    try:
        sql = (Path(__file__).resolve().parents[1] / 'db/init.sql').read_text(encoding='utf-8')
        await connection.execute(sql)
    finally:
        await connection.close(timeout=2)


if __name__ == '__main__':
    try:
        asyncio.run(initialize_database())
    except Exception:
        print('[FAIL] 数据库建表失败；请确认 DB_URL 指向已存在的数据库，且账号有建表及安装 vector 扩展的权限。')
        raise SystemExit(1)
    print('[OK] 已补齐配置数据库中的表结构，保留已有记录。')
