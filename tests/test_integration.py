import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MemoryIntegrationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "memory.sqlite3"

    def run_cli(self, *arguments, expected_status=0):
        result = subprocess.run(
            [
                sys.executable, "-m", "selflearningai",
                "--기억파일", os.fspath(self.database), *arguments,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        self.assertEqual(result.returncode, expected_status, result.stderr)
        return result

    def test_evidence_changes_judgment_and_preserves_history(self):
        topic = "공원의 야간 개방"
        self.assertIn("저장된 증거가 없습니다", self.run_cli("판단", topic).stdout)
        self.run_cli("학습", topic, "개방", "현장 관찰", "출입문이 열려 있었다.")
        self.assertIn("잠정 판단 — 개방", self.run_cli("판단", topic).stdout)

        self.run_cli("학습", topic, "폐쇄", "관리 공지", "야간 폐쇄 공지를 확인했다.")
        self.assertIn("판단 보류", self.run_cli("판단", topic).stdout)
        self.run_cli("학습", topic, "폐쇄", "야간 방문", "출입문이 잠겨 있었다.")
        self.assertIn("잠정 판단 — 폐쇄", self.run_cli("판단", topic).stdout)

        history = self.run_cli("기록", topic).stdout
        self.assertEqual(len(history.splitlines()), 3)
        self.assertIn("개방 | 현장 관찰 | 출입문이 열려 있었다.", history)

    def test_validation_and_lock(self):
        topic = "관측 결과"
        self.run_cli("학습", topic, "맑음", "관측소", "구름이 없었다.")
        duplicate = self.run_cli(
            "학습", topic, "맑음", "  관측소  ", "구름이 없었다.", expected_status=1
        )
        self.assertIn("최신 기록과 같은 증거", duplicate.stderr)
        invalid = self.run_cli("학습", topic, "흐림", "다른 관측소", " ", expected_status=1)
        self.assertIn("증거", invalid.stderr)
        with sqlite3.connect(self.database) as connection:
            for query in (
                "UPDATE evidence SET value = '흐림'",
                "DELETE FROM evidence",
                """INSERT OR REPLACE INTO evidence (id, topic, value, source, note)
                   VALUES (1, '관측 결과', '흐림', '관측소', '교체 시도')""",
            ):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "잠긴 증거"):
                    connection.execute(query)
        history = self.run_cli("기록", topic).stdout
        self.assertEqual(len(history.splitlines()), 1)
        self.assertIn("맑음", history)


    def test_source_correction_uses_only_latest_evidence(self):
        topic = "관측 결과"
        self.run_cli("학습", topic, "맑음", "관측소", "첫 보고")
        self.run_cli("학습", topic, "맑음", "관측소", "추가 확인")
        self.run_cli("학습", topic, "흐림", "다른 관측소", "별도 관측")
        self.assertIn("판단 보류", self.run_cli("판단", topic).stdout)
        self.run_cli("학습", topic, "흐림", "관측소", "정정 보고")
        judgment = self.run_cli("판단", topic).stdout
        self.assertIn("잠정 판단 — 흐림", judgment)
        self.assertIn("흐림 (출처 2개)", judgment)
        self.assertNotIn("맑음", judgment)
        self.assertEqual(len(self.run_cli("기록", topic).stdout.splitlines()), 4)

    def test_opening_legacy_memory_preserves_evidence_and_lock(self):
        with sqlite3.connect(self.database) as connection:
            connection.executescript("""
                CREATE TABLE evidence (
                    id INTEGER PRIMARY KEY,
                    topic TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL,
                    note TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (topic, source)
                );
                CREATE TRIGGER lock_evidence_update BEFORE UPDATE ON evidence
                BEGIN
                    SELECT RAISE(ABORT, '잠긴 증거');
                END;
                CREATE TRIGGER lock_evidence_delete BEFORE DELETE ON evidence
                BEGIN
                    SELECT RAISE(ABORT, '잠긴 증거');
                END;
                INSERT INTO evidence VALUES
                    (7, '관측 결과', '맑음', '관측소', '첫 보고', '2026-11-27 00:00:00');
            """)
        self.run_cli("학습", "관측 결과", "흐림", "관측소", "정정 보고")
        history = self.run_cli("기록", "관측 결과").stdout
        self.assertIn("7. 맑음 | 관측소 | 첫 보고 | 2026-11-27 00:00:00 UTC", history)
        self.assertIn("8. 흐림 | 관측소 | 정정 보고", history)
        with sqlite3.connect(self.database) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "잠긴 증거"):
                connection.execute("DELETE FROM evidence")

    def test_exploration_reprioritizes_after_source_correction(self):
        def explore():
            return self.run_cli("탐구").stdout

        self.assertIn("주제를 찾지 못했습니다", explore())
        self.run_cli("학습", "공원 운영", "개방", "현장 관찰", "첫 방문")
        self.run_cli("학습", "공원 운영", "폐쇄", "관리소", "첫 공지")
        self.run_cli("학습", "도서관 운영", "개방", "현장 관찰", "첫 방문")

        candidate = explore()
        self.assertIn("다음 탐구 주제 — 공원 운영", candidate)
        self.assertIn("‘개방’ 1개, ‘폐쇄’ 1개", candidate)
        self.assertIn("확인할 질문", candidate)

        self.run_cli("학습", "공원 운영", "개방", "관리소", "정정 공지")
        candidate = explore()
        self.assertIn("다음 탐구 주제 — 도서관 운영", candidate)
        self.assertIn("출처가 1개뿐입니다", candidate)
        self.assertIn("폐쇄 | 관리소 | 첫 공지", self.run_cli("기록", "공원 운영").stdout)

        self.run_cli("학습", "도서관 운영", "개방", "관리소", "운영 안내")
        self.assertIn("주제를 찾지 못했습니다", explore())

    def test_exploration_prefers_ties_then_smaller_gaps(self):
        for topic, leading, other in (
            ("근소한 차이", 2, 1),
            ("큰 차이", 3, 1),
            ("동률", 1, 1),
        ):
            for value, count in (("찬성", leading), ("반대", other)):
                for index in range(count):
                    self.run_cli("학습", topic, value, f"{value} 출처 {index}", "관측 내용")
        self.assertIn("다음 탐구 주제 — 동률", self.run_cli("탐구").stdout)
        self.run_cli("학습", "동률", "찬성", "반대 출처 0", "정정")
        self.assertIn("다음 탐구 주제 — 근소한 차이", self.run_cli("탐구").stdout)

    def test_exploration_searches_local_documents_and_keeps_memory_unchanged(self):
        self.run_cli("학습", "공원 운영", "개방", "현장 관찰", "첫 방문")
        document = self.database.with_name("운영.txt")
        data = "제목\n공원   운영 기준은 매월 개정된다.\n".encode("utf-8")
        document.write_bytes(data)
        unrelated = self.database.with_name("기타.txt")
        unrelated.write_text("도서관 운영 안내", encoding="utf-8")

        result = self.run_cli(
            "탐구", "--자료", str(document), "--자료", str(document), "--자료", str(unrelated)
        ).stdout
        self.assertEqual(result.count("증거 후보 —"), 1)
        self.assertIn(f"{document.resolve()}:2", result)
        self.assertIn("공원 운영 기준은 매월 개정된다.", result)
        self.assertIn(hashlib.sha256(data).hexdigest(), result)
        self.assertIn("주제와 일치하는 구절을 찾지 못했습니다", self.run_cli(
            "탐구", "--자료", str(unrelated)
        ).stdout)
        history = self.run_cli("기록", "공원 운영").stdout
        self.assertEqual(len(history.splitlines()), 1)
        self.assertIn("개방 | 현장 관찰 | 첫 방문", history)

    def test_exploration_reports_unsupported_document(self):
        self.run_cli("학습", "공원 운영", "개방", "현장 관찰", "첫 방문")
        document = self.database.with_name("손상.txt")
        document.write_bytes(bytes([255]))
        result = self.run_cli("탐구", "--자료", str(document), expected_status=1)
        self.assertIn("UTF-8 문서를 지정해야 합니다", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
