import os
from contextlib import contextmanager
from datetime import date

DATABASE_URL = os.environ.get("DATABASE_URL", "")
ALLOWED_LIBRARY_UPDATE = {"status", "rating", "notes", "date_completed", "cover_url"}
_PG = bool(DATABASE_URL)

if _PG:
    import psycopg2
    import psycopg2.extras

    @contextmanager
    def get_db():
        conn = psycopg2.connect(DATABASE_URL)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _exec(conn, sql, params=()):
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql.replace("?", "%s"), list(params))
        return cur

else:
    import sqlite3
    _DB_PATH = os.path.join(os.path.dirname(__file__), "mediavault.db")

    @contextmanager
    def get_db():
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _exec(conn, sql, params=()):
        return conn.execute(sql, list(params))


def _rows(cur):
    return [dict(r) for r in cur.fetchall()]


def _row(cur):
    r = cur.fetchone()
    return dict(r) if r else None


def _insert_id(conn, sql, params=()):
    if _PG:
        cur = _exec(conn, sql + " RETURNING id", params)
        return cur.fetchone()["id"]
    cur = _exec(conn, sql, params)
    return cur.lastrowid


# ── Schema ────────────────────────────────────────────────────────────────────

_PK = "SERIAL PRIMARY KEY" if _PG else "INTEGER PRIMARY KEY AUTOINCREMENT"

_DDL = f"""
CREATE TABLE IF NOT EXISTS library (
    id             {_PK},
    title          TEXT NOT NULL,
    type           TEXT NOT NULL,
    status         TEXT NOT NULL,
    rating         REAL,
    notes          TEXT,
    date_added     TEXT NOT NULL,
    date_completed TEXT,
    cover_url      TEXT
);
CREATE TABLE IF NOT EXISTS watchlist (
    id         {_PK},
    title      TEXT NOT NULL,
    type       TEXT NOT NULL,
    notes      TEXT,
    date_added TEXT NOT NULL,
    cover_url  TEXT
);
"""


def init_db():
    with get_db() as conn:
        for stmt in _DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                _exec(conn, stmt)
        if not _PG:
            # SQLite-only: add columns to existing databases safely
            for sql in [
                "ALTER TABLE library ADD COLUMN cover_url TEXT",
                "ALTER TABLE watchlist ADD COLUMN cover_url TEXT",
            ]:
                try:
                    _exec(conn, sql)
                except Exception:
                    pass


# ── Library ───────────────────────────────────────────────────────────────────

def library_all(type_=None, status=None):
    sql = "SELECT * FROM library WHERE 1=1"
    params = []
    if type_:
        sql += " AND type = ?"
        params.append(type_)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY date_added DESC"
    with get_db() as conn:
        return _rows(_exec(conn, sql, params))


def library_add(title, type_, status, rating=None, notes=None, cover_url=None):
    today = date.today().isoformat()
    with get_db() as conn:
        return _insert_id(
            conn,
            "INSERT INTO library (title, type, status, rating, notes, date_added, cover_url) VALUES (?,?,?,?,?,?,?)",
            (title, type_, status, rating, notes, today, cover_url),
        )


def library_update(id, **kw):
    fields = {k: v for k, v in kw.items() if k in ALLOWED_LIBRARY_UPDATE}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [id]
    with get_db() as conn:
        _exec(conn, f"UPDATE library SET {set_clause} WHERE id = ?", values)


def library_delete(id):
    with get_db() as conn:
        _exec(conn, "DELETE FROM library WHERE id = ?", (id,))


# ── Watchlist ─────────────────────────────────────────────────────────────────

def watchlist_all(type_=None):
    sql = "SELECT * FROM watchlist WHERE 1=1"
    params = []
    if type_:
        sql += " AND type = ?"
        params.append(type_)
    sql += " ORDER BY date_added DESC"
    with get_db() as conn:
        return _rows(_exec(conn, sql, params))


def watchlist_add(title, type_, notes=None, cover_url=None):
    today = date.today().isoformat()
    with get_db() as conn:
        return _insert_id(
            conn,
            "INSERT INTO watchlist (title, type, notes, date_added, cover_url) VALUES (?,?,?,?,?)",
            (title, type_, notes, today, cover_url),
        )


def watchlist_delete(id):
    with get_db() as conn:
        deleted = _row(_exec(conn, "SELECT * FROM watchlist WHERE id = ?", (id,)))
        _exec(conn, "DELETE FROM watchlist WHERE id = ?", (id,))
    return deleted


def watchlist_move(id, status="plan_to_watch"):
    with get_db() as conn:
        item = _row(_exec(conn, "SELECT * FROM watchlist WHERE id = ?", (id,)))
        if item is None:
            return None
        today = date.today().isoformat()
        new_id = _insert_id(
            conn,
            "INSERT INTO library (title, type, status, rating, notes, date_added, cover_url) VALUES (?,?,?,?,?,?,?)",
            (item["title"], item["type"], status, None, item.get("notes"), today, item.get("cover_url")),
        )
        _exec(conn, "DELETE FROM watchlist WHERE id = ?", (id,))
        return new_id
