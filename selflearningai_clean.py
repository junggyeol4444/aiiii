import argparse
import hashlib
import os
import sqlite3
import stat
import unicodedata
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory


EDITION = "CLEAN"


# 장기 기억
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


# 자료 탐구와 인용 검사
MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_MATCHES_PER_DOCUMENT = 3
CONTEXT_CHARACTERS = 80


@dataclass(frozen=True)
class Passage:
    path: Path
    line_number: int
    text: str
    sha256: str


def read_document(path):
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"일반 파일을 지정해야 합니다: {path}")
    with path.open("rb") as stream:
        data = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError(f"문서는 1 MiB 이하여야 합니다: {path}")
    try:
        return data.decode("utf-8-sig"), hashlib.sha256(data).hexdigest()
    except UnicodeDecodeError as error:
        raise ValueError(f"UTF-8 문서를 지정해야 합니다: {path}") from error


def display_text(text):
    return "".join(character if character.isprintable() else "�" for character in text)


def matching_excerpt(topic, line):
    line = " ".join(unicodedata.normalize("NFC", line).split())
    offset = line.find(topic)
    if offset == -1:
        return None
    start = max(0, offset - CONTEXT_CHARACTERS)
    end = offset + len(topic) + CONTEXT_CHARACTERS
    excerpt = line[start:end]
    if start:
        excerpt = "…" + excerpt
    if end < len(line):
        excerpt += "…"
    return display_text(excerpt)


def verify_passage(topic, document, line_number, expected_digest=None):
    if expected_digest is not None and (
        len(expected_digest) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in expected_digest)
    ):
        raise ValueError("검색 결과에 표시된 64자리 SHA-256을 입력해야 합니다.")
    path = Path(document).resolve()
    content, digest = read_document(path)
    if expected_digest is not None and digest != expected_digest.lower():
        raise ValueError("파일 SHA-256이 검색 결과와 다릅니다. 다시 탐구하세요.")
    lines = content.splitlines()
    if not 1 <= line_number <= len(lines):
        raise ValueError("자료에 해당 줄 번호가 없습니다.")
    excerpt = matching_excerpt(topic, lines[line_number - 1])
    if excerpt is None:
        raise ValueError("지정한 줄에서 주제 문구를 찾지 못했습니다.")
    return Passage(path, line_number, excerpt, digest)


def find_passages(topic, documents):
    passages = []
    seen = set()
    for document in documents:
        path = Path(document).resolve()
        if path in seen:
            continue
        seen.add(path)
        content, digest = read_document(path)
        matches = 0
        for number, line in enumerate(content.splitlines(), start=1):
            excerpt = matching_excerpt(topic, line)
            if excerpt is None:
                continue
            passages.append(Passage(path, number, excerpt, digest))
            matches += 1
            if matches == MAX_MATCHES_PER_DOCUMENT:
                break
    return passages


# 실행 명령
def main():
    test_mode = EDITION == "TEST"
    parser = argparse.ArgumentParser(description=f"SelfLearningAI {EDITION} 장기 기억과 탐구")
    if test_mode:
        parser.add_argument("--기억파일", dest="database", help="테스트용 기억 파일 경로")
    commands = parser.add_subparsers(dest="command", required=True)
    learn = commands.add_parser("학습", help="출처와 증거를 기억에 통합")
    for label in ("주제", "주장", "출처", "증거"):
        learn.add_argument(label)
    for name, description in (
        ("판단", "현재 잠정 판단 조회"),
        ("기록", "저장된 증거 전체 조회"),
    ):
        commands.add_parser(name, help=description).add_argument("주제")
    explore = commands.add_parser("탐구", help="다음 탐구 주제를 선택하고 지정한 자료 조사")
    explore.add_argument("--자료", dest="documents", action="append", default=[], metavar="파일")
    cite = commands.add_parser("인용학습", help="원본을 재확인한 구절을 증거로 통합")
    for label in ("주제", "주장", "출처", "파일"):
        cite.add_argument(label)
    cite.add_argument("줄번호", type=int)
    cite.add_argument("sha256", metavar="SHA-256", nargs="?")
    args = parser.parse_args()
    path = CLEAN_DATABASE_NAME
    if test_mode:
        legacy = Path("memory.sqlite3")
        default = Path("test.sqlite3")
        path = args.database
        if path is None:
            path = legacy if not default.exists() and legacy.is_file() else default
    memory = Memory(path, test_mode=test_mode)
    try:
        memory.initialize()
        if args.command == "학습":
            entry = memory.learn(args.주제, args.주장, args.출처, args.증거)
            print(f"검사 통과. 증거 {entry}번을 통합하고 잠갔습니다.")
        elif args.command == "인용학습":
            topic = normalize(args.주제, "주제", 200)
            passage = verify_passage(topic, args.파일, args.줄번호, args.sha256)
            note = (
                f"{passage.text} [파일 {str(passage.path)!r}, "
                f"줄 {passage.line_number}, SHA-256 {passage.sha256}]"
            )
            entry = memory.learn(topic, args.주장, args.출처, note)
            check = "원본 검사 통과" if args.sha256 is not None else "현재 파일의 인용 위치 확인"
            print(f"{check}. 증거 {entry}번을 통합하고 잠갔습니다.")
        elif args.command == "판단":
            results = memory.assess(args.주제)
            if not results:
                print("저장된 증거가 없습니다.")
            else:
                value, count = results[0]
                if len(results) > 1 and results[1][1] == count:
                    print("판단 보류. 가장 많은 지지를 얻은 주장이 동률입니다.")
                else:
                    print(f"잠정 판단 — {value}")
                for value, count in results:
                    print(f"- {value} (출처 {count}개)")
        elif args.command == "탐구":
            candidate = memory.next_exploration()
            if candidate is None:
                print("현재 기억에서 추가 확인이 필요한 주제를 찾지 못했습니다.")
            else:
                topic, sources, leading, other, leading_votes, other_votes = candidate
                if other is None:
                    reason = "현재 출처가 1개뿐입니다."
                    question = f"다른 출처에서도 ‘{leading}’ 주장을 뒷받침하나요?"
                else:
                    reason = (
                        f"출처 {sources}개 중 ‘{leading}’ {leading_votes}개, "
                        f"‘{other}’ {other_votes}개로 의견이 갈립니다."
                    )
                    question = f"‘{leading}’과(와) ‘{other}’을(를) 구분할 증거는 무엇인가요?"
                passages = find_passages(topic, args.documents)
                print(f"다음 탐구 주제 — {topic}")
                print(f"선택 이유 — {reason}")
                print(f"확인할 질문 — {question}")
                if args.documents and not passages:
                    print("지정한 자료에서 주제와 일치하는 구절을 찾지 못했습니다.")
                for passage in passages:
                    print(f"증거 후보 — {display_text(str(passage.path))}:{passage.line_number}")
                    print(f"  인용 — {passage.text}")
                    print(f"  파일 SHA-256 — {passage.sha256}")
        else:
            records = memory.history(args.주제)
            if not records:
                print("저장된 증거가 없습니다.")
            for entry, value, source, note, timestamp in records:
                print(f"{entry}. {value} | {source} | {note} | {timestamp} UTC")
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"오류 — {error}\n")


if __name__ == "__main__":
    main()
