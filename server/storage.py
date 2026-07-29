"""SQLite 存储层：初始化表结构与 CRUD。"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Generator, Optional

from config import DB_PATH

logger = logging.getLogger(__name__)

_local = threading.local()
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn() -> sqlite3.Connection:
    """线程本地连接。"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


@contextmanager
def transaction() -> Generator[sqlite3.Connection, None, None]:
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    """创建表结构，清理 30 天前 events。"""
    with transaction() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY,
              username TEXT UNIQUE,
              password_hash TEXT,
              created_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              type TEXT,
              data TEXT,
              ts INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

            CREATE TABLE IF NOT EXISTS conversations (
              id TEXT PRIMARY KEY,
              title TEXT,
              last_message_at INTEGER,
              last_activity_at INTEGER,
              updated_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              conversation_id TEXT,
              role TEXT,
              content TEXT,
              ts INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, ts);

            CREATE TABLE IF NOT EXISTS automations (
              id TEXT PRIMARY KEY,
              name TEXT,
              status TEXT,
              last_run_at INTEGER,
              next_run_at INTEGER,
              updated_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS automation_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              automation_id TEXT,
              status TEXT,
              started_at INTEGER,
              finished_at INTEGER,
              result TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_runs_auto ON automation_runs(automation_id, started_at);

            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY,
              team TEXT,
              subject TEXT,
              status TEXT,
              owner TEXT,
              description TEXT,
              updated_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_team ON tasks(team);

            CREATE TABLE IF NOT EXISTS agent_status (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              workbuddy_running INTEGER DEFAULT 0,
              workbuddy_pid INTEGER,
              last_activity_at INTEGER,
              active_conversation_id TEXT,
              active_conversation_title TEXT,
              cpu_percent REAL,
              memory_mb REAL,
              uptime_seconds INTEGER,
              screenshot_updated_at INTEGER,
              raw_json TEXT,
              updated_at INTEGER
            );
            """
        )
        # 确保 agent_status 有一行
        conn.execute(
            "INSERT OR IGNORE INTO agent_status (id, updated_at) VALUES (1, ?)",
            (int(time.time()),),
        )
        # 兼容旧表：补列（ALTER TABLE 忽略已存在的列）
        for col, typ in [
            ("cpu_count", "INTEGER"),
            ("memory_total_mb", "REAL"),
            ("memory_percent", "REAL"),
            ("disk_used_gb", "REAL"),
            ("disk_total_gb", "REAL"),
            ("disk_percent", "REAL"),
        ]:
            try:
                conn.execute(f"ALTER TABLE agent_status ADD COLUMN {col} {typ}")
            except Exception:
                pass  # 列已存在
        # 清理 30 天前 events
        cutoff = int(time.time()) - 30 * 24 * 3600
        cur = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
        if cur.rowcount:
            logger.info("已清理 %d 条 30 天前的 events", cur.rowcount)
    logger.info("SQLite 初始化完成: %s", DB_PATH)


# ─── users ───


def get_user_by_username(username: str) -> Optional[dict[str, Any]]:
    row = get_conn().execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    return dict(row) if row else None


def create_user(username: str, password_hash: str) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, int(time.time())),
        )


def ensure_admin(username: str, password_hash: str) -> None:
    """若 admin 不存在则创建。"""
    existing = get_user_by_username(username)
    if existing is None:
        create_user(username, password_hash)
        logger.info("已创建默认用户: %s", username)


# ─── events ───


def insert_event(event_type: str, data: Any, ts: Optional[int] = None) -> int:
    if ts is None:
        ts = int(time.time())
    data_str = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    with transaction() as conn:
        cur = conn.execute(
            "INSERT INTO events (type, data, ts) VALUES (?, ?, ?)",
            (event_type, data_str, ts),
        )
        return int(cur.lastrowid)


def list_events(limit: int = 100, since: Optional[int] = None) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 1000))
    if since is not None:
        rows = get_conn().execute(
            "SELECT * FROM events WHERE ts >= ? ORDER BY ts DESC, id DESC LIMIT ?",
            (since, limit),
        ).fetchall()
    else:
        rows = get_conn().execute(
            "SELECT * FROM events ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["data"] = json.loads(d["data"]) if d["data"] else {}
        except (json.JSONDecodeError, TypeError):
            pass
        result.append(d)
    return result


# ─── conversations / messages ───


def upsert_conversation(
    conv_id: str,
    title: str = "",
    last_message_at: Optional[int] = None,
    last_activity_at: Optional[int] = None,
) -> None:
    now = int(time.time())
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO conversations (id, title, last_message_at, last_activity_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title = COALESCE(NULLIF(excluded.title, ''), conversations.title),
              last_message_at = COALESCE(excluded.last_message_at, conversations.last_message_at),
              last_activity_at = COALESCE(excluded.last_activity_at, conversations.last_activity_at),
              updated_at = excluded.updated_at
            """,
            (
                conv_id,
                title or "",
                last_message_at or now,
                last_activity_at or now,
                now,
            ),
        )


def list_conversations(limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    rows = get_conn().execute(
        """
        SELECT * FROM conversations
        ORDER BY COALESCE(last_activity_at, updated_at, 0) DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def replace_conversations(items: list) -> None:
    """全量替换会话列表（agent sync 调用）。"""
    now = int(time.time())
    with transaction() as conn:
        conn.execute("DELETE FROM conversations")
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                conn.execute(
                    """INSERT INTO conversations (id, title, last_message_at, last_activity_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         title=excluded.title, last_activity_at=excluded.last_activity_at, updated_at=excluded.updated_at""",
                    (str(item["id"]), item.get("title") or "", item.get("last_message_at") or now,
                     item.get("last_activity_at") or now, now),
                )


def insert_message(conversation_id: str, role: str, content: str, ts: Optional[int] = None) -> int:
    if ts is None:
        ts = int(time.time())
    with transaction() as conn:
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, ts),
        )
        # 同步更新会话时间
        conn.execute(
            """
            UPDATE conversations SET
              last_message_at = ?,
              last_activity_at = ?,
              updated_at = ?
            WHERE id = ?
            """,
            (ts, ts, ts, conversation_id),
        )
        # 若会话不存在则创建
        conn.execute(
            """
            INSERT OR IGNORE INTO conversations (id, title, last_message_at, last_activity_at, updated_at)
            VALUES (?, '', ?, ?, ?)
            """,
            (conversation_id, ts, ts, ts),
        )
        return int(cur.lastrowid)


def list_messages(
    conversation_id: str,
    limit: int = 50,
    before: Optional[int] = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    if before is not None:
        rows = get_conn().execute(
            """
            SELECT * FROM messages
            WHERE conversation_id = ? AND ts < ?
            ORDER BY ts DESC LIMIT ?
            """,
            (conversation_id, before, limit),
        ).fetchall()
    else:
        rows = get_conn().execute(
            """
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY ts DESC LIMIT ?
            """,
            (conversation_id, limit),
        ).fetchall()
    # 返回按时间正序
    result = [dict(r) for r in reversed(rows)]
    return result


# ─── automations ───


def upsert_automation(
    auto_id: str,
    name: str = "",
    status: str = "ACTIVE",
    last_run_at: Optional[int] = None,
    next_run_at: Optional[int] = None,
) -> None:
    now = int(time.time())
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO automations (id, name, status, last_run_at, next_run_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              name = COALESCE(NULLIF(excluded.name, ''), automations.name),
              status = COALESCE(excluded.status, automations.status),
              last_run_at = COALESCE(excluded.last_run_at, automations.last_run_at),
              next_run_at = COALESCE(excluded.next_run_at, automations.next_run_at),
              updated_at = excluded.updated_at
            """,
            (auto_id, name or "", status, last_run_at, next_run_at, now),
        )


def list_automations() -> list[dict[str, Any]]:
    rows = get_conn().execute(
        "SELECT * FROM automations ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def replace_automations(items: list) -> None:
    """全量替换自动化列表（agent sync 调用）。"""
    now = int(time.time())
    with transaction() as conn:
        conn.execute("DELETE FROM automations")
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                conn.execute(
                    """INSERT INTO automations (id, name, status, last_run_at, next_run_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (str(item["id"]), item.get("name") or "", item.get("status") or "ACTIVE",
                     item.get("last_run_at"), item.get("next_run_at"), now),
                )


def get_automation(auto_id: str) -> Optional[dict[str, Any]]:
    row = get_conn().execute(
        "SELECT * FROM automations WHERE id = ?", (auto_id,)
    ).fetchone()
    return dict(row) if row else None


def update_automation_status(auto_id: str, status: str) -> bool:
    with transaction() as conn:
        cur = conn.execute(
            "UPDATE automations SET status = ?, updated_at = ? WHERE id = ?",
            (status, int(time.time()), auto_id),
        )
        return cur.rowcount > 0


def insert_automation_run(
    automation_id: str,
    status: str = "pending",
    started_at: Optional[int] = None,
    finished_at: Optional[int] = None,
    result: str = "",
) -> int:
    if started_at is None:
        started_at = int(time.time())
    with transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO automation_runs (automation_id, status, started_at, finished_at, result)
            VALUES (?, ?, ?, ?, ?)
            """,
            (automation_id, status, started_at, finished_at, result),
        )
        return int(cur.lastrowid)


def list_automation_runs(automation_id: str, limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    rows = get_conn().execute(
        """
        SELECT * FROM automation_runs
        WHERE automation_id = ?
        ORDER BY started_at DESC LIMIT ?
        """,
        (automation_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ─── tasks ───


def upsert_task(
    task_id: str,
    team: str = "",
    subject: str = "",
    status: str = "pending",
    owner: str = "",
    description: str = "",
) -> None:
    now = int(time.time())
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO tasks (id, team, subject, status, owner, description, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              team = COALESCE(NULLIF(excluded.team, ''), tasks.team),
              subject = COALESCE(NULLIF(excluded.subject, ''), tasks.subject),
              status = COALESCE(excluded.status, tasks.status),
              owner = COALESCE(excluded.owner, tasks.owner),
              description = COALESCE(excluded.description, tasks.description),
              updated_at = excluded.updated_at
            """,
            (task_id, team, subject, status, owner, description, now),
        )


def list_tasks(team: Optional[str] = None) -> list[dict[str, Any]]:
    if team:
        rows = get_conn().execute(
            "SELECT * FROM tasks WHERE team = ? ORDER BY updated_at DESC",
            (team,),
        ).fetchall()
    else:
        rows = get_conn().execute(
            "SELECT * FROM tasks ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ─── agent status ───


def update_agent_status(data: dict[str, Any]) -> None:
    """根据 agent 上报的 status 更新缓存（只更新 data 中出现的字段）。"""
    now = int(time.time())
    sets = ["updated_at = ?", "raw_json = ?"]
    values: list[Any] = [now, json.dumps(data, ensure_ascii=False)]
    mapping = [
        ("workbuddy_running", "workbuddy_running"),
        ("workbuddy_pid", "workbuddy_pid"),
        ("last_activity_at", "last_activity_at"),
        ("active_conversation_id", "active_conversation_id"),
        ("active_conversation_title", "active_conversation_title"),
        ("cpu_percent", "cpu_percent"),
        ("cpu_count", "cpu_count"),
        ("memory_mb", "memory_mb"),
        ("memory_total_mb", "memory_total_mb"),
        ("memory_percent", "memory_percent"),
        ("disk_used_gb", "disk_used_gb"),
        ("disk_total_gb", "disk_total_gb"),
        ("disk_percent", "disk_percent"),
        ("uptime_seconds", "uptime_seconds"),
        ("screenshot_updated_at", "screenshot_updated_at"),
    ]
    for data_key, col in mapping:
        if data_key in data:
            sets.append(f"{col} = ?")
            if data_key == "workbuddy_running":
                values.append(1 if data[data_key] else 0)
            else:
                values.append(data[data_key])
    sql = f"UPDATE agent_status SET {', '.join(sets)} WHERE id = 1"
    with transaction() as conn:
        conn.execute(sql, values)


def set_screenshot_updated_at(ts: Optional[int] = None) -> None:
    if ts is None:
        ts = int(time.time())
    with transaction() as conn:
        conn.execute(
            "UPDATE agent_status SET screenshot_updated_at = ?, updated_at = ? WHERE id = 1",
            (ts, int(time.time())),
        )


def get_agent_status_row() -> dict[str, Any]:
    row = get_conn().execute("SELECT * FROM agent_status WHERE id = 1").fetchone()
    if not row:
        return {}
    d = dict(row)
    d["workbuddy_running"] = bool(d.get("workbuddy_running"))
    return d
