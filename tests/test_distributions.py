from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]


class DistributionIntegrationTest(unittest.TestCase):
    def run_program(self, program, *arguments, cwd, expected_status=0):
        result = subprocess.run(
            [sys.executable, str(program), *arguments],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        self.assertEqual(result.returncode, expected_status, result.stderr)
        return result

    def test_archives_have_separate_launchers_and_memories(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            topic = "관측소 운영"
            self.run_program(
                ROOT / "selflearningai_test.py",
                "학습", topic, "개방", "관측소", "출입 확인",
                cwd=workspace,
            )
            evaluation = workspace / "evaluation"
            evaluation.mkdir()
            (evaluation / "result.txt").write_text("평가 자료", encoding="utf-8")
            output = workspace / "dist"
            self.run_program(
                ROOT / "tools/build_distributions.py",
                "--test-db", "test.sqlite3",
                "--evaluation-dir", "evaluation",
                "--output-dir", "dist",
                cwd=workspace,
            )

            shared = {
                "README.md",
                "selflearningai/__init__.py",
                "selflearningai/cli.py",
                "selflearningai/memory.py",
                "selflearningai/research.py",
            }
            test_workspace = workspace / "test"
            clean_workspace = workspace / "clean"
            with (
                ZipFile(output / "SelfLearningAI-TEST.zip") as test_zip,
                ZipFile(output / "SelfLearningAI-CLEAN.zip") as clean_zip,
            ):
                self.assertCountEqual(
                    test_zip.namelist(),
                    shared | {"selflearningai_test.py", "test.sqlite3", "evaluation/result.txt"},
                )
                self.assertCountEqual(clean_zip.namelist(), shared | {"selflearningai_clean.py"})
                for path in shared:
                    self.assertEqual(test_zip.read(path), clean_zip.read(path), path)
                test_zip.extractall(test_workspace)
                clean_zip.extractall(clean_workspace)

            test_result = self.run_program(
                "selflearningai_test.py", "판단", topic, cwd=test_workspace,
            )
            self.assertIn("잠정 판단 — 개방", test_result.stdout)
            clean_result = self.run_program(
                "selflearningai_clean.py", "판단", topic, cwd=clean_workspace,
            )
            self.assertIn("저장된 증거가 없습니다", clean_result.stdout)
            self.run_program(
                "selflearningai_clean.py", "학습", topic, "폐쇄", "사용자 관측", "정문 확인",
                cwd=clean_workspace,
            )
            clean_result = self.run_program(
                "selflearningai_clean.py", "판단", topic, cwd=clean_workspace,
            )
            self.assertIn("잠정 판단 — 폐쇄", clean_result.stdout)

            test_bytes = (test_workspace / "test.sqlite3").read_bytes()
            clean_file = clean_workspace / "clean.sqlite3"
            clean_file.write_bytes(test_bytes)
            rejected = self.run_program(
                "selflearningai_clean.py", "판단", topic, cwd=clean_workspace, expected_status=1,
            )
            self.assertIn("클린", rejected.stderr)
            self.assertEqual(clean_file.read_bytes(), test_bytes)
