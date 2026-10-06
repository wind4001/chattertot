-- lym-sound 数据库初始化脚本
CREATE EXTENSION IF NOT EXISTS vector;

-- 对话历史（多轮记忆）
--
-- 设计说明：当前是「全局单流」——没有用户身份，所有对话写入同一张表，
-- LLM 上下文取最近 N 条。故不设 conversation_id（早期版本有，但从未写入，
-- 一直是 NULL，已移除）。将来若引入多用户/多孩子，再加 user_id 或 conversation_id。
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_id_desc ON messages(id DESC);

-- 长期记忆档案（会话结束时自动摘要更新，注入 system prompt）
--
-- scope：记忆归属。当前无身份信号（声纹每轮自确立、不持久化），恒为 'default'。
-- 预留此列是为了「阶段 3：声纹自动建档」上线时，按人分档案（scope = speaker_id）而不用改表。
--
-- last_message_id：摘要水位线——只摘要 id 大于它的消息，避免重复摘要。
CREATE TABLE IF NOT EXISTS profile (
    id SERIAL PRIMARY KEY,
    scope TEXT NOT NULL UNIQUE DEFAULT 'default',
    facts TEXT DEFAULT '',
    last_message_id INTEGER DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 说明：曾有计划用表存全局声纹（speakers），现已改为「每轮对话自成声纹」
-- （唤醒句/首句确立，静默超时释放），声纹只存内存、不落库，故不建表。
