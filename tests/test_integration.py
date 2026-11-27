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
            "학습", topic, "흐림", "  관측소  ", "새 관측", expected_status=1
        )
        self.assertIn("이미 등록된 출처", duplicate.stderr)
        invalid = self.run_cli("학습", topic, "흐림", "다른 관측소", " ", expected_status=1)
        self.assertIn("증거", invalid.stderr)
        with sqlite3.connect(self.database) as connection:
            for query in ("UPDATE evidence SET value = '흐림'", "DELETE FROM evidence"):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "잠긴 증거"):
                    connection.execute(query)
        history = self.run_cli("기록", topic).stdout
        self.assertEqual(len(history.splitlines()), 1)
        self.assertIn("맑음", history)


if __name__ == "__main__":
    unittest.main()
