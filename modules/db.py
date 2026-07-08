"""
?°ì´?°ë² ?´ì¤(SQLite) ê´??ëª¨ë
- documents ?ì´ë¸??ëë¡?ê³ ì/Q&A/?¸ë??ìë£ë? ëª¨ë ê´ë¦¬í©?ë¤.
- ì½ë©????ëª¨ë¥´?ë, ???ì¼? ê±°ì ê±´ëë¦??¼ì´ ?ìµ?ë¤.
"""
import sqlite3
import os
from datetime import datetime, timedelta

BASE_DIR = "/tmp"
import pathlib
pathlib.Path(BASE_DIR + "/data").mkdir(parents=True, exist_ok=True)
pathlib.Path(BASE_DIR + "/data/uploads").mkdir(parents=True, exist_ok=True)
DB_PATH = os.path.join(BASE_DIR, "data", "app.db")
import shutil as _shutil
_src = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'app.db'))
if not os.path.exists(DB_PATH) and os.path.exists(_src):
    _shutil.copy2(_src, DB_PATH)
UPLOAD_DIR = os.path.join(BASE_DIR, "data", "uploads")

# ??ë¬¸ìë¡??ì??ê¸°ì? (???¨ì)
NEW_BADGE_DAYS = 14

CATEGORY_LABELS = {
    "notice": "?ì½ì²?ê³ ì/ê°?´ë?¼ì¸",
    "qna": "?ì½ì²?Q&A",
    "seminar": "?¬ë´ ?¸ë????ë£",
}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,           -- notice / qna / seminar
            title TEXT NOT NULL,
            team_tag TEXT,                    -- RA / QC_QA / ALL (?¤ë¬´ ê°?´ë ???? ?í¸)
            uploader TEXT,
            presenter TEXT,                   -- ?¸ë???ë°í??(?¸ë????ë£??
            event_date TEXT,                  -- ?¸ë???ë°í????(?¸ë????ë£??
            source_url TEXT,                  -- ?ì½ì²??ë¬¸ ???¸ë? ë§í¬
            original_filename TEXT,
            stored_path TEXT,                 -- ?ë²????¥ë ?¤ì  ?ì¼ ê²½ë¡
            extracted_text TEXT,              -- ì¶ì¶??ë³¸ë¬¸ ?ì¤??(ê²??AI ë¶ì??
            upload_date TEXT NOT NULL
        )
        """
    )
    # ê¸°ì¡´ DB????ì»¬ë¼???ì ?ê² ì¶ê? (?´ë? ?ì¼ë©?ì¡°ì©??ë¬´ì)
    for ddl in (
        "ALTER TABLE documents ADD COLUMN origin TEXT DEFAULT 'manual'",
        "ALTER TABLE documents ADD COLUMN external_guid TEXT",
        "ALTER TABLE documents ADD COLUMN board_name TEXT",
        "ALTER TABLE documents ADD COLUMN impact_note TEXT",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass  # ì»¬ë¼???´ë? ì¡´ì¬?ë ê²½ì°

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS guide_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_category TEXT NOT NULL,     -- ?? validation
            title TEXT NOT NULL,
            body TEXT NOT NULL,               -- ?ì/?ì ê¸°ì?/?¤ë¬´ ?ì°¨ ??ë³¸ë¬¸(ë§í¬?¤ì´ ?ì¤??
            qna_json TEXT,                    -- [{"question":..,"answer":..}, ...] JSON ë¬¸ì??            status TEXT NOT NULL DEFAULT 'draft',  -- draft / reviewed
            created_date TEXT NOT NULL,
            updated_date TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,          -- data/uploads ?ì ?¤ì  ?ì¼ëª?            file_seq INTEGER,
            created_date TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            note_text TEXT NOT NULL,
            created_date TEXT NOT NULL
        )
        """
    )
    # ?ì  ë°©ì(ë¬¸ì??ë©ëª¨ 1ê°? documents.impact_note)?¼ë¡ ??¥ë ë©ëª¨ë¥?    # ???¤í°ì»?ë©ëª¨ ë°©ì(document_notes, ?¬ë¬ ê°??ì )?¼ë¡ ??ë²ë§ ??²¨ì¤ë??
    old_notes = conn.execute(
        "SELECT id, impact_note, upload_date FROM documents WHERE impact_note IS NOT NULL AND impact_note != ''"
    ).fetchall()
    for row in old_notes:
        already = conn.execute(
            "SELECT COUNT(*) as c FROM document_notes WHERE document_id = ?", (row["id"],)
        ).fetchone()["c"]
        if already == 0:
            conn.execute(
                "INSERT INTO document_notes (document_id, note_text, created_date) VALUES (?, ?, ?)",
                (row["id"], row["impact_note"], row["upload_date"]),
            )
    conn.commit()
    conn.close()


def insert_document(category, title, extracted_text, team_tag=None, uploader=None,
                     presenter=None, event_date=None, source_url=None,
                     original_filename=None, stored_path=None, origin="manual",
                     external_guid=None, board_name=None, upload_date=None):
    conn = get_db()
    cur = conn.execute(
        """
        INSERT INTO documents
            (category, title, team_tag, uploader, presenter, event_date,
             source_url, original_filename, stored_path, extracted_text, upload_date,
             origin, external_guid, board_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            category, title, team_tag, uploader, presenter, event_date,
            source_url, original_filename, stored_path, extracted_text,
            upload_date or datetime.now().isoformat(timespec="seconds"),
            origin, external_guid, board_name,
        ),
    )
    conn.commit()
    doc_id = cur.lastrowid
    conn.close()
    return doc_id


def get_document_by_external_guid(external_guid):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM documents WHERE external_guid = ?", (external_guid,)
    ).fetchone()
    conn.close()
    return row


def delete_document(doc_id):
    conn = get_db()
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()


def update_extracted_text(doc_id, extracted_text):
    conn = get_db()
    conn.execute("UPDATE documents SET extracted_text = ? WHERE id = ?", (extracted_text, doc_id))
    conn.commit()
    conn.close()


def append_extracted_text(doc_id, extra_text):
    if not extra_text:
        return
    conn = get_db()
    row = conn.execute("SELECT extracted_text FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if row is None:
        conn.close()
        return
    combined = ((row["extracted_text"] or "") + "\n\n" + extra_text).strip()
    conn.execute("UPDATE documents SET extracted_text = ? WHERE id = ?", (combined, doc_id))
    conn.commit()
    conn.close()


def insert_attachment(document_id, filename, stored_path, file_seq=None):
    conn = get_db()
    conn.execute(
        """
        INSERT INTO document_attachments (document_id, filename, stored_path, file_seq, created_date)
        VALUES (?, ?, ?, ?, ?)
        """,
        (document_id, filename, stored_path, file_seq, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def get_attachments(document_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM document_attachments WHERE document_id = ? ORDER BY file_seq", (document_id,)
    ).fetchall()
    conn.close()
    return rows


def get_attachment(attachment_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM document_attachments WHERE id = ?", (attachment_id,)
    ).fetchone()
    conn.close()
    return row


def get_all_attachments():
    conn = get_db()
    rows = conn.execute("SELECT * FROM document_attachments").fetchall()
    conn.close()
    return rows


def delete_attachment(attachment_id):
    conn = get_db()
    conn.execute("DELETE FROM document_attachments WHERE id = ?", (attachment_id,))
    conn.commit()
    conn.close()


def has_attachments(document_id):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM document_attachments WHERE document_id = ?", (document_id,)
    ).fetchone()
    conn.close()
    return row["c"] > 0


def insert_note(document_id, note_text):
    conn = get_db()
    conn.execute(
        "INSERT INTO document_notes (document_id, note_text, created_date) VALUES (?, ?, ?)",
        (document_id, note_text, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def get_notes(document_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM document_notes WHERE document_id = ? ORDER BY created_date DESC", (document_id,)
    ).fetchall()
    conn.close()
    return rows


def get_latest_note(document_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM document_notes WHERE document_id = ? ORDER BY created_date DESC LIMIT 1",
        (document_id,),
    ).fetchone()
    conn.close()
    return row


def get_note(note_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM document_notes WHERE id = ?", (note_id,)).fetchone()
    conn.close()
    return row


def update_note(note_id, note_text):
    conn = get_db()
    conn.execute("UPDATE document_notes SET note_text = ? WHERE id = ?", (note_text, note_id))
    conn.commit()
    conn.close()


def delete_note(note_id):
    conn = get_db()
    conn.execute("DELETE FROM document_notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()


def category_counts():
    conn = get_db()
    rows = conn.execute(
        "SELECT category, COUNT(*) as c FROM documents GROUP BY category"
    ).fetchall()
    conn.close()
    return {r["category"]: r["c"] for r in rows}


def get_all_documents(category=None):
    conn = get_db()
    if category:
        rows = conn.execute(
            "SELECT * FROM documents WHERE category = ? ORDER BY upload_date DESC", (category,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM documents ORDER BY upload_date DESC").fetchall()
    conn.close()
    return rows


def get_document(doc_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    return row


def get_recent_documents(days=NEW_BADGE_DAYS, limit=20):
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM documents WHERE upload_date >= ? ORDER BY upload_date DESC LIMIT ?",
        (cutoff, limit),
    ).fetchall()
    conn.close()
    return rows


def is_new(upload_date_str, days=NEW_BADGE_DAYS):
    try:
        d = datetime.fromisoformat(upload_date_str)
    except ValueError:
        return False
    if d.tzinfo is not None:
        d = d.astimezone().replace(tzinfo=None)
    return (datetime.now() - d) <= timedelta(days=days)


def document_count():
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) as c FROM documents").fetchone()
    conn.close()
    return row["c"]


# ---------- ?¤ë¬´ ?´ì¤ ì§?ë² ?´ì¤ (guide_notes) ----------

def insert_guide_note(topic_category, title, body, qna_json="[]", status="draft"):
    conn = get_db()
    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO guide_notes (topic_category, title, body, qna_json, status, created_date, updated_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (topic_category, title, body, qna_json, status, now, now),
    )
    conn.commit()
    note_id = cur.lastrowid
    conn.close()
    return note_id


def get_all_guide_notes():
    conn = get_db()
    rows = conn.execute("SELECT * FROM guide_notes ORDER BY topic_category, title").fetchall()
    conn.close()
    return rows


def get_guide_note(note_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM guide_notes WHERE id = ?", (note_id,)).fetchone()
    conn.close()
    return row


def update_guide_note(note_id, topic_category, title, body, qna_json, status):
    conn = get_db()
    conn.execute(
        """
        UPDATE guide_notes
        SET topic_category = ?, title = ?, body = ?, qna_json = ?, status = ?, updated_date = ?
        WHERE id = ?
        """,
        (topic_category, title, body, qna_json, status, datetime.now().isoformat(timespec="seconds"), note_id),
    )
    conn.commit()
    conn.close()


def guide_note_count():
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) as c FROM guide_notes").fetchone()
    conn.close()
    return row["c"]
