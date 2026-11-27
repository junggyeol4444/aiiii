import sqlite3
import unicodedata
from contextlib import closing


CREATE_EVIDENCE = """
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY,
    topic TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    note TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

LOCK_UPDATE = """
CREATE TRIGGER IF NOT EXISTS lock_evidence_update
BEFORE UPDATE ON evidence
BEGIN
    SELECT RAISE(ABORT, '잠긴 증거는 수정할 수 없습니다');
END;
"""

LOCK_DELETE = """
CREATE TRIGGER IF NOT EXISTS lock_evidence_delete
BEFORE DELETE ON evidence
BEGIN
    SELECT RAISE(ABORT, '잠긴 증거는 삭제할 수 없습니다');
END;
"""


LOCK_REPLACE = """
CREATE TRIGGER IF NOT EXISTS lock_evidence_replace
BEFORE INSERT ON evidence
WHEN EXISTS (SELECT 1 FROM evidence WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, '잠긴 증거는 교체할 수 없습니다');
END;
"""


def normalize(text, label, limit):
    text = " ".join(unicodedata.normalize("NFC", text).split())
    if not text or len(text) > limit:
        raise ValueError(f"{label}은(는) 1~{limit}자여야 합니다.")
    if any(unicodedata.category(character) == "Cc" for character in text):
        raise ValueError(f"{label}에 제어 문자를 넣을 수 없습니다.")
    return text


class Memory:
    def __init__(self, path):
        self.path = path

    def initialize(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            if connection.execute("PRAGMA user_version").fetchone()[0] == 1:
                return
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 1:
                return
            if version != 0:
                raise ValueError(f"지원하지 않는 기억 파일 버전입니다 ({version}).")
            legacy = connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'evidence'"
            ).fetchone()
            if legacy:
                connection.execute("ALTER TABLE evidence RENAME TO legacy_evidence")
            connection.execute(CREATE_EVIDENCE)
            if legacy:
                connection.execute("""
                    INSERT INTO evidence (id, topic, value, source, note, recorded_at)
                    SELECT id, topic, value, source, note, recorded_at FROM legacy_evidence
                """)
                connection.execute("DROP TABLE legacy_evidence")
            connection.execute(
                "CREATE INDEX evidence_topic_source ON evidence (topic, source, id)"
            )
            connection.execute(LOCK_UPDATE)
            connection.execute(LOCK_DELETE)
            connection.execute(LOCK_REPLACE)
            connection.execute("PRAGMA user_version = 1")

    def learn(self, topic, value, source, note):
        # 검사에 통과한 입력을 한 트랜잭션에서 통합한다.
        record = {
            "topic": normalize(topic, "주제", 200),
            "value": normalize(value, "주장", 500),
            "source": normalize(source, "출처", 500),
            "note": normalize(note, "증거", 4000),
        }
        with closing(sqlite3.connect(self.path)) as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO evidence (topic, value, source, note)
                SELECT :topic, :value, :source, :note
                WHERE NOT EXISTS (
                    SELECT 1 FROM evidence
                    WHERE id = (
                        SELECT MAX(id) FROM evidence WHERE topic = :topic AND source = :source
                    ) AND value = :value AND note = :note
                )
                """,
                record,
            )
            if cursor.rowcount == 0:
                raise ValueError("이 출처의 최신 기록과 같은 증거입니다.")
            return cursor.lastrowid

    def assess(self, topic):
        topic = normalize(topic, "주제", 200)
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(
                """
                SELECT value, COUNT(*) AS votes
                FROM evidence
                WHERE id IN (
                    SELECT MAX(id) FROM evidence WHERE topic = ? GROUP BY source
                )
                GROUP BY value ORDER BY votes DESC, value
                """,
                (topic,),
            ).fetchall()

    def history(self, topic):
        topic = normalize(topic, "주제", 200)
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(
                """
                SELECT id, value, source, note, recorded_at
                FROM evidence WHERE topic = ? ORDER BY id
                """,
                (topic,),
            ).fetchall()
