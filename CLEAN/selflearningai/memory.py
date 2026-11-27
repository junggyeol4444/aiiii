import os
import sqlite3
import unicodedata
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory


CLEAN_DATABASE_NAME = "clean.sqlite3"
CLEAN_APPLICATION_ID = 0x534C4149  # "SLAI"
TEST_APPLICATION_ID = 0x534C4154  # "SLAT"


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


def initialize_schema(connection):
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


class Memory:
    def __init__(self, path, *, test_mode=False):
        self.path = Path(path).absolute()
        self.test_mode = test_mode

    @contextmanager
    def connect(self, *, initialize=False):
        if self.test_mode and (
            self.path.name.casefold() == CLEAN_DATABASE_NAME
            or self.path.resolve().name.casefold() == CLEAN_DATABASE_NAME
        ):
            raise ValueError("클린 기억 파일은 테스트 모드에서 사용할 수 없습니다.")

        expected_id = TEST_APPLICATION_ID if self.test_mode else CLEAN_APPLICATION_ID
        target = self.path.as_uri()
        mode = "rwc" if self.test_mode and initialize else "rw"
        with closing(sqlite3.connect(f"{target}?mode={mode}", uri=True)) as connection:
            if initialize:
                connection.execute("BEGIN IMMEDIATE")
            application_id = connection.execute("PRAGMA application_id").fetchone()[0]
            legacy_test = self.test_mode and initialize and application_id == 0
            if application_id != expected_id and not legacy_test:
                label = "테스트" if self.test_mode else "클린"
                raise ValueError(f"{label} 모드와 다른 종류의 기억 파일입니다. 테스트와 클린 파일을 분리하세요.")
            yield connection

    def initialize(self):
        if not self.test_mode and not self.path.exists():
            self.create_clean_database()
        with self.connect(initialize=True) as connection, connection:
            initialize_schema(connection)
            if self.test_mode and connection.execute("PRAGMA application_id").fetchone()[0] == 0:
                connection.execute(f"PRAGMA application_id = {TEST_APPLICATION_ID}")

    def create_clean_database(self):
        # 초기화가 끝난 빈 DB만 공개해 동시 실행에서도 반쪽짜리 파일을 읽지 않는다.
        with TemporaryDirectory(dir=self.path.parent) as directory:
            temporary_path = Path(directory) / CLEAN_DATABASE_NAME
            with closing(sqlite3.connect(temporary_path)) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                initialize_schema(connection)
                connection.execute(f"PRAGMA application_id = {CLEAN_APPLICATION_ID}")
            try:
                os.link(temporary_path, self.path)
            except FileExistsError:
                pass

    def learn(self, topic, value, source, note):
        # 검사에 통과한 입력을 한 트랜잭션에서 통합한다.
        record = {
            "topic": normalize(topic, "주제", 200),
            "value": normalize(value, "주장", 500),
            "source": normalize(source, "출처", 500),
            "note": normalize(note, "증거", 4000),
        }
        with self.connect() as connection, connection:
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
        with self.connect() as connection:
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

    def next_exploration(self):
        with self.connect() as connection:
            return connection.execute(
                """
                WITH latest AS (
                    SELECT MAX(id) AS id FROM evidence GROUP BY topic, source
                ),
                support AS (
                    SELECT topic, value, COUNT(*) AS votes, MAX(evidence.id) AS newest
                    FROM latest JOIN evidence ON evidence.id = latest.id
                    GROUP BY topic, value
                ),
                ranked AS (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY topic ORDER BY votes DESC, value
                           ) AS position
                    FROM support
                ),
                topics AS (
                    SELECT topic, SUM(votes) AS sources, MAX(newest) AS newest,
                           MAX(CASE WHEN position = 1 THEN value END) AS leading_value,
                           MAX(CASE WHEN position = 2 THEN value END) AS other_value,
                           MAX(CASE WHEN position = 1 THEN votes END) AS leading_votes,
                           MAX(CASE WHEN position = 2 THEN votes END) AS other_votes
                    FROM ranked GROUP BY topic
                )
                SELECT topic, sources, leading_value, other_value, leading_votes, other_votes
                FROM topics
                WHERE other_votes IS NOT NULL OR sources = 1
                ORDER BY CASE
                             WHEN leading_votes = other_votes THEN 0
                             WHEN other_votes IS NOT NULL THEN 1
                             ELSE 2
                         END,
                         leading_votes - other_votes, newest DESC, topic
                LIMIT 1
                """
            ).fetchone()

    def history(self, topic):
        topic = normalize(topic, "주제", 200)
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT id, value, source, note, recorded_at
                FROM evidence WHERE topic = ? ORDER BY id
                """,
                (topic,),
            ).fetchall()
