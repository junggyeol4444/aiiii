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
            [sys.executable, "-E", "-s", "-S", "-B", "-X", "utf8", str(program), *arguments],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        self.assertEqual(result.returncode, expected_status, result.stderr)
        return result

    def test_archives_have_independent_program_folders_and_memories(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            topic = "관측소 운영"
            self.run_program(
                ROOT / "TEST/run.py",
                "--기억파일", str(workspace / "test.sqlite3"),
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

            program_files = {
                "run.py",
                "selflearningai/__init__.py",
                "selflearningai/cli.py",
                "selflearningai/memory.py",
                "selflearningai/research.py",
            }
            test_workspace = workspace / "test-install" / "TEST"
            clean_workspace = workspace / "clean-install" / "CLEAN"
            with (
                ZipFile(output / "SelfLearningAI-TEST.zip") as test_zip,
                ZipFile(output / "SelfLearningAI-CLEAN.zip") as clean_zip,
            ):
                self.assertCountEqual(
                    test_zip.namelist(),
                    {f"TEST/{name}" for name in program_files}
                    | {"TEST/README.md", "TEST/test.sqlite3", "TEST/evaluation/result.txt"},
                )
                self.assertCountEqual(
                    clean_zip.namelist(),
                    {f"CLEAN/{name}" for name in program_files} | {"CLEAN/README.md"},
                )
                for edition, archive in (("TEST", test_zip), ("CLEAN", clean_zip)):
                    for name in program_files:
                        path = f"{edition}/{name}"
                        self.assertEqual(archive.read(path), (ROOT / path).read_bytes(), path)
                test_zip.extractall(test_workspace.parent)
                clean_zip.extractall(clean_workspace.parent)

            outside_cwd = workspace / "outside-cwd"
            outside_cwd.mkdir()
            test_result = self.run_program(
                test_workspace / "run.py", "판단", topic, cwd=outside_cwd,
            )
            self.assertIn("잠정 판단 — 개방", test_result.stdout)
            clean_result = self.run_program(
                clean_workspace / "run.py", "판단", topic, cwd=outside_cwd,
            )
            self.assertIn("저장된 증거가 없습니다", clean_result.stdout)
            self.run_program(
                clean_workspace / "run.py", "학습", topic, "폐쇄", "사용자 관측", "정문 확인",
                cwd=outside_cwd,
            )
            clean_result = self.run_program(
                clean_workspace / "run.py", "판단", topic, cwd=outside_cwd,
            )
            self.assertIn("잠정 판단 — 폐쇄", clean_result.stdout)

            test_bytes = (test_workspace / "test.sqlite3").read_bytes()
            clean_file = clean_workspace / "clean.sqlite3"
            clean_file.write_bytes(test_bytes)
            rejected = self.run_program(
                clean_workspace / "run.py", "판단", topic, cwd=outside_cwd, expected_status=1,
            )
            self.assertIn("클린", rejected.stderr)
            self.assertEqual(clean_file.read_bytes(), test_bytes)
            self.assertEqual(list(outside_cwd.iterdir()), [])
