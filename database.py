import sqlite3
from contextlib import contextmanager
from datetime import date
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "mediavault.db")

ALLOWED_LIBRARY_UPDATE = {"status", "rating", "notes", "date_completed", "cover_url"}


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_add_show_type(conn):
    """Drop CHECK constraints so 'show' is a valid type."""
    try:
        conn.execute("INSERT INTO library (title,type,status,date_added) VALUES ('__probe__','show','plan_to_watch','2000-01-01')")
        conn.execute("DELETE FROM library WHERE title='__probe__'")
        # Already works, no migration needed
        return
    except Exception:
        pass
    # Recreate library without CHECK
    conn.executescript("""
        CREATE TABLE library_v2 (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            title         TEXT NOT NULL,
            type          TEXT NOT NULL,
            status        TEXT NOT NULL,
            rating        REAL,
            notes         TEXT,
            cover_url     TEXT,
            date_added    TEXT NOT NULL,
            date_completed TEXT
        );
        INSERT INTO library_v2 SELECT id,title,type,status,rating,notes,cover_url,date_added,date_completed FROM library;
        DROP TABLE library;
        ALTER TABLE library_v2 RENAME TO library;

        CREATE TABLE watchlist_v2 (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT NOT NULL,
            type       TEXT NOT NULL,
            notes      TEXT,
            cover_url  TEXT,
            date_added TEXT NOT NULL
        );
        INSERT INTO watchlist_v2 SELECT id,title,type,notes,cover_url,date_added FROM watchlist;
        DROP TABLE watchlist;
        ALTER TABLE watchlist_v2 RENAME TO watchlist;
    """)


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS library (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                title         TEXT NOT NULL,
                type          TEXT NOT NULL,
                status        TEXT NOT NULL CHECK(status IN ('plan_to_watch','in_progress','completed','dropped')),
                rating        REAL,
                notes         TEXT,
                date_added    TEXT NOT NULL,
                date_completed TEXT,
                cover_url     TEXT
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT NOT NULL,
                type       TEXT NOT NULL,
                notes      TEXT,
                date_added TEXT NOT NULL,
                cover_url  TEXT
            );
            """
        )
        # Safe migration for existing databases
        for sql in [
            "ALTER TABLE library ADD COLUMN cover_url TEXT",
            "ALTER TABLE watchlist ADD COLUMN cover_url TEXT",
        ]:
            try:
                conn.execute(sql)
            except Exception:
                pass  # column already exists
        _migrate_add_show_type(conn)


# ── Library ──────────────────────────────────────────────────────────────────

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
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def library_add(title, type_, status, rating=None, notes=None, cover_url=None):
    today = date.today().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO library (title, type, status, rating, notes, date_added, cover_url) VALUES (?,?,?,?,?,?,?)",
            (title, type_, status, rating, notes, today, cover_url),
        )
        return cur.lastrowid


def library_update(id, **kw):
    fields = {k: v for k, v in kw.items() if k in ALLOWED_LIBRARY_UPDATE}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [id]
    with get_db() as conn:
        conn.execute(f"UPDATE library SET {set_clause} WHERE id = ?", values)


def library_delete(id):
    with get_db() as conn:
        conn.execute("DELETE FROM library WHERE id = ?", (id,))


# ── Watchlist ────────────────────────────────────────────────────────────────

def watchlist_all(type_=None):
    sql = "SELECT * FROM watchlist WHERE 1=1"
    params = []
    if type_:
        sql += " AND type = ?"
        params.append(type_)
    sql += " ORDER BY date_added DESC"
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def watchlist_add(title, type_, notes=None, cover_url=None):
    today = date.today().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO watchlist (title, type, notes, date_added, cover_url) VALUES (?,?,?,?,?)",
            (title, type_, notes, today, cover_url),
        )
        return cur.lastrowid


def watchlist_delete(id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM watchlist WHERE id = ?", (id,)).fetchone()
        deleted = dict(row) if row else None
        conn.execute("DELETE FROM watchlist WHERE id = ?", (id,))
    return deleted


def watchlist_move(id, status="plan_to_watch"):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM watchlist WHERE id = ?", (id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        today = date.today().isoformat()
        cur = conn.execute(
            "INSERT INTO library (title, type, status, rating, notes, date_added, cover_url) VALUES (?,?,?,?,?,?,?)",
            (item["title"], item["type"], status, None, item.get("notes"), today, item.get("cover_url")),
        )
        conn.execute("DELETE FROM watchlist WHERE id = ?", (id,))
        return cur.lastrowid
