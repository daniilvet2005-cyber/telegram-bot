import sqlite3
from datetime import datetime

def connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def init_db(con: sqlite3.Connection):
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS songs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number INTEGER UNIQUE NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS favorites(
        user_id INTEGER NOT NULL,
        song_id INTEGER NOT NULL,
        PRIMARY KEY(user_id, song_id)
    )
    """)

    # FTS5 (если доступно)
    try:
        cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS songs_fts USING fts5(
          title, body, content='songs', content_rowid='id'
        )
        """)
        cur.executescript("""
        CREATE TRIGGER IF NOT EXISTS songs_ai AFTER INSERT ON songs BEGIN
          INSERT INTO songs_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
        END;
        CREATE TRIGGER IF NOT EXISTS songs_ad AFTER DELETE ON songs BEGIN
          INSERT INTO songs_fts(songs_fts, rowid, title, body) VALUES('delete', old.id, old.title, old.body);
        END;
        CREATE TRIGGER IF NOT EXISTS songs_au AFTER UPDATE ON songs BEGIN
          INSERT INTO songs_fts(songs_fts, rowid, title, body) VALUES('delete', old.id, old.title, old.body);
          INSERT INTO songs_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
        END;
        """)
    except Exception:
        # если FTS5 нет — просто работаем без неё (будет fallback LIKE)
        pass

    con.commit()

def add_or_update_song(con: sqlite3.Connection, number: int, title: str, body: str):
    con.execute(
        "INSERT INTO songs(number,title,body,updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(number) DO UPDATE SET title=excluded.title, body=excluded.body, updated_at=excluded.updated_at",
        (number, title, body, datetime.utcnow().isoformat()),
    )
    con.commit()

def delete_song_by_number(con: sqlite3.Connection, number: int) -> bool:
    cur = con.execute("DELETE FROM songs WHERE number=?", (number,))
    con.commit()
    return cur.rowcount > 0

def get_song_by_number(con: sqlite3.Connection, number: int):
    return con.execute("SELECT * FROM songs WHERE number=?", (number,)).fetchone()

def get_song_by_id(con: sqlite3.Connection, song_id: int):
    return con.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone()

def count_songs(con: sqlite3.Connection) -> int:
    return con.execute("SELECT COUNT(*) AS c FROM songs").fetchone()["c"]

def list_songs_page(con: sqlite3.Connection, page: int, page_size: int):
    offset = (page - 1) * page_size
    return con.execute(
        "SELECT * FROM songs ORDER BY number LIMIT ? OFFSET ?",
        (page_size, offset)
    ).fetchall()

def search_songs(con: sqlite3.Connection, query: str, limit: int = 20):
    # Пытаемся через FTS5
    return con.execute(
        "SELECT s.* FROM songs_fts f JOIN songs s ON s.id=f.rowid "
        "WHERE songs_fts MATCH ? ORDER BY rank LIMIT ?",
        (query, limit)
    ).fetchall()

def search_songs_fallback_like(con: sqlite3.Connection, query: str, limit: int = 20):
    q = f"%{query}%"
    return con.execute(
        "SELECT * FROM songs WHERE title LIKE ? OR body LIKE ? ORDER BY number LIMIT ?",
        (q, q, limit)
    ).fetchall()

def is_favorite(con: sqlite3.Connection, user_id: int, song_id: int) -> bool:
    r = con.execute(
        "SELECT 1 FROM favorites WHERE user_id=? AND song_id=?",
        (user_id, song_id)
    ).fetchone()
    return r is not None

def toggle_favorite(con: sqlite3.Connection, user_id: int, song_id: int) -> bool:
    if is_favorite(con, user_id, song_id):
        con.execute("DELETE FROM favorites WHERE user_id=? AND song_id=?", (user_id, song_id))
        con.commit()
        return False
    con.execute("INSERT OR IGNORE INTO favorites(user_id, song_id) VALUES(?,?)", (user_id, song_id))
    con.commit()
    return True

def count_favorites(con: sqlite3.Connection, user_id: int) -> int:
    return con.execute("SELECT COUNT(*) AS c FROM favorites WHERE user_id=?", (user_id,)).fetchone()["c"]

def list_favorites_page(con: sqlite3.Connection, user_id: int, page: int, page_size: int):
    offset = (page - 1) * page_size
    return con.execute(
        "SELECT s.* FROM favorites f JOIN songs s ON s.id=f.song_id "
        "WHERE f.user_id=? ORDER BY s.number LIMIT ? OFFSET ?",
        (user_id, page_size, offset)
    ).fetchall()
