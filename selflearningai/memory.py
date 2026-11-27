import sqlite3
import unicodedata
from contextlib import closing


SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY,
    topic TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    note TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (topic, source)
);

CREATE TRIGGER IF NOT EXISTS lock_evidence_update
BEFORE UPDATE ON evidence
BEGIN
    SELECT RAISE(ABORT, '잠긴 증거는 수정할 수 없습니다');
END;

CREATE TRIGGER IF NOT EXISTS lock_evidence_delete
BEFORE DELETE ON evidence
BEGIN
    SELECT RAISE(ABORT, '잠긴 증거는 삭제할 수 없습니다');
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
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript(SCHEMA)

    def learn(self, topic, value, source, note):
        # 검사에 통과한 입력을 한 트랜잭션에서 통합한다.
        record = (
            normalize(topic, "주제", 200),
            normalize(value, "주장", 500),
            normalize(source, "출처", 500),
            normalize(note, "증거", 4000),
        )
        with closing(sqlite3.connect(self.path)) as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO evidence (topic, value, source, note)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (topic, source) DO NOTHING
                """,
                record,
            )
            if cursor.rowcount == 0:
                raise ValueError("이 주제에 이미 등록된 출처입니다.")
            return cursor.lastrowid

    def assess(self, topic):
        topic = normalize(topic, "주제", 200)
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(
                """
                SELECT value, COUNT(*) AS votes
                FROM evidence WHERE topic = ?
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
