import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProgramIntegrationCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)
        self.test_workspace = self.workspace / "TEST"
        self.clean_workspace = self.workspace / "CLEAN"
        self.test_workspace.mkdir()
        self.clean_workspace.mkdir()
        self.database = self.test_workspace / "memory.sqlite3"

    def run_cli(self, *arguments, expected_status=0):
        return self.run_test_cli(
            "--기억파일", os.fspath(self.database), *arguments, expected_status=expected_status,
        )

    def run_clean_cli(self, *arguments, expected_status=0):
        return self.run_program("CLEAN", *arguments, expected_status=expected_status)

    def run_test_cli(self, *arguments, expected_status=0):
        return self.run_program("TEST", *arguments, expected_status=expected_status)

    def run_program(self, distribution, *arguments, expected_status):
        destination = self.workspace / distribution
        launcher = destination / "run.py"
        if not launcher.is_file():
            shutil.copytree(
                ROOT / distribution,
                destination,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("*.sqlite3*", "__pycache__", "evaluation"),
            )
        result = subprocess.run(
            [sys.executable, "-E", "-s", "-S", os.fspath(launcher), *arguments],
            cwd=self.workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        if expected_status is None:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        else:
            self.assertEqual(result.returncode, expected_status, result.stderr)
        return result


class CleanProgramIntegrationTest(ProgramIntegrationCase):
    def test_clean_and_test_memory_are_isolated(self):
        topic = "공원 운영"
        clean_path = self.clean_workspace / "clean.sqlite3"
        test_path = self.test_workspace / "test.sqlite3"

        self.assertIn("저장된 증거가 없습니다", self.run_clean_cli("기록", topic).stdout)
        self.assertTrue(clean_path.is_file())
        self.assertFalse(test_path.exists())

        self.run_test_cli("학습", topic, "개방", "관리소", "테스트 공지")
        self.assertTrue(test_path.is_file())
        test_baseline = test_path.read_bytes()

        test_history = self.run_test_cli("기록", topic).stdout
        self.assertIn("개방 | 관리소 | 테스트 공지", test_history)
        clean_history = self.run_clean_cli("기록", topic).stdout
        self.assertIn("저장된 증거가 없습니다", clean_history)

        self.run_clean_cli("학습", topic, "폐쇄", "사용자 관찰", "정문이 닫혀 있었다.")
        document = self.database.with_name("공지.txt")
        document.write_text("공원 운영은 야간에 중단된다.", encoding="utf-8")
        self.run_clean_cli("인용학습", topic, "폐쇄", "관리소", str(document), "1")
        clean_history = self.run_clean_cli("기록", topic).stdout
        self.assertIn("폐쇄 | 사용자 관찰 | 정문이 닫혀 있었다.", clean_history)
        self.assertIn("공원 운영은 야간에 중단된다.", clean_history)
        self.assertNotIn("테스트 공지", clean_history)
        self.assertIn("폐쇄 (출처 2개)", self.run_clean_cli("판단", topic).stdout)
        self.assertEqual(test_path.read_bytes(), test_baseline)
        self.assertEqual(list(self.workspace.glob("*.sqlite3")), [])

    def test_launchers_cannot_switch_modes(self):
        for launcher, mode in ((self.run_clean_cli, "테스트"), (self.run_test_cli, "클린")):
            with self.subTest(mode=mode):
                launcher("--모드", mode, "기록", "공원 운영", expected_status=2)
        self.assertEqual(list(self.workspace.rglob("*.sqlite3")), [])

    def test_launchers_reject_other_memory_files_including_aliases(self):
        topic = "공원 운영"
        clean_path = self.clean_workspace / "clean.sqlite3"
        self.run_clean_cli("학습", topic, "개방", "관리소", "클린 공지")
        clean_baseline = clean_path.read_bytes()
        alias = self.database.with_name("별칭.sqlite3")
        os.link(clean_path, alias)

        for path in (clean_path, alias):
            with self.subTest(path=path):
                rejected = self.run_test_cli(
                    "--기억파일", str(path),
                    "학습", topic, "개방", "관리소", "운영 공지",
                    expected_status=None,
                )
                self.assertIn("클린", rejected.stderr)
        self.assertEqual(clean_path.read_bytes(), clean_baseline)

        self.run_test_cli("학습", topic, "폐쇄", "관리소", "테스트 공지")
        test_path = self.test_workspace / "test.sqlite3"
        test_baseline = test_path.read_bytes()
        clean_path.unlink()
        os.link(test_path, clean_path)

        for command in (("기록", topic), ("학습", topic, "개방", "관리소", "덮어쓰기 시도")):
            with self.subTest(command=command):
                rejected = self.run_clean_cli(*command, expected_status=None)
                self.assertIn("테스트", rejected.stderr)
        self.assertEqual(test_path.read_bytes(), test_baseline)
        self.assertEqual(alias.read_bytes(), clean_baseline)

    def test_existing_marked_clean_memory_allows_learning(self):
        clean_path = self.clean_workspace / "clean.sqlite3"
        with sqlite3.connect(clean_path) as connection:
            connection.executescript("""
                PRAGMA application_id = 0x534C4149;
                PRAGMA user_version = 1;
                CREATE TABLE evidence (
                    id INTEGER PRIMARY KEY,
                    topic TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL,
                    note TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

        self.run_clean_cli("학습", "공원 운영", "개방", "관리소", "새 공지")
        self.assertIn("개방 | 관리소 | 새 공지", self.run_clean_cli("기록", "공원 운영").stdout)

    def test_legacy_memory_is_only_visible_in_test_launcher(self):
        topic = "공원 운영"
        self.run_cli("학습", topic, "개방", "관리소", "기존 공지")
        self.assertIn("저장된 증거가 없습니다", self.run_clean_cli("기록", topic).stdout)
        test_history = self.run_test_cli("기록", topic).stdout
        self.assertIn("개방 | 관리소 | 기존 공지", test_history)

        self.run_clean_cli("--기억파일", str(self.database), "기록", topic, expected_status=2)


class TestProgramIntegrationTest(ProgramIntegrationCase):
    def write_observations(self, *observations):
        fields = ("주제", "주장", "출처", "증거")
        document = self.workspace / "관측.json"
        document.write_text(
            json.dumps([dict(zip(fields, observation)) for observation in observations], ensure_ascii=False),
            encoding="utf-8",
        )
        return document

    def learn_observations(self, *observations, continuous=False, expected_status=0):
        document = self.write_observations(*observations)
        options = ("--계속",) if continuous else ()
        return self.run_cli("자율학습", "--자료", str(document), *options, expected_status=expected_status)

    def test_autonomous_learning_selects_one_topic_by_distinct_sources_then_name(self):
        park = "가로수길 공원 운영"
        trail = "나루 산책로 운영"
        garden = "다솜 정원 운영"
        repeated = (garden, "개방", "현장", "문이 열려 있었다.")
        self.learn_observations(
            repeated, repeated, repeated,
            (trail, "개방", "현장", "산책로를 이용할 수 있었다."),
            (trail, "개방", "운영 공지", "입장할 수 있다고 적혀 있었다."),
            (park, "개방", "현장", "정문이 열려 있었다."),
            (park, "개방", "관리소", "운영 중으로 확인됐다."),
            (park, "개방", "관리소", "운영 중으로 확인됐다."),
        )
        self.assertIn("개방 (출처 2개)", self.run_cli("판단", park).stdout)
        self.assertEqual(len(self.run_cli("기록", park).stdout.splitlines()), 2)
        for topic in (trail, garden):
            self.assertIn("저장된 증거가 없습니다", self.run_cli("기록", topic).stdout)

    def test_autonomous_learning_follows_exploration_rank_for_uncertain_topics(self):
        tie = "공원의 야간 개방"
        singleton = "도서관의 주말 개관"
        new_topic = "체육관의 오전 운영"
        replay_only = "천문대의 야간 관측"
        self.run_cli("학습", tie, "개방", "관리소", "지난 공지는 개방이었다.")
        self.run_cli("학습", tie, "폐쇄", "현장", "출입 통제 중이었다.")
        self.run_cli("학습", singleton, "개관", "도서관", "기존 공지에 적혀 있었다.")
        self.run_cli("학습", replay_only, "운영", "천문대", "이전 일정에 적혀 있었다.")
        self.run_cli("학습", replay_only, "중단", "현장", "장비 점검 중이었다.")

        self.learn_observations(
            (replay_only, "운영", "천문대", "이전 일정에 적혀 있었다."),
            (singleton, "개관", "현장", "출입문이 열려 있었다."),
            (new_topic, "운영", "현장", "실내 운동장이 열려 있었다."),
            (new_topic, "운영", "관리소", "운영 시간표에 적혀 있었다."),
            (new_topic, "운영", "별도 문의", "예약 가능한 시간이었다."),
            (tie, "폐쇄", "현장 문의", "입장할 수 없었다."),
            (tie, "폐쇄", "새 공지", "폐쇄 일정이 안내됐다."),
        )
        self.assertIn("폐쇄 (출처 3개)", self.run_cli("판단", tie).stdout)
        self.assertIn("지난 공지는 개방이었다.", self.run_cli("기록", tie).stdout)
        self.assertEqual(len(self.run_cli("기록", singleton).stdout.splitlines()), 1)
        self.assertIn("저장된 증거가 없습니다", self.run_cli("기록", new_topic).stdout)

    def test_autonomous_learning_continues_until_all_topics_are_learned(self):
        uncertain = "공원의 야간 개방"
        strongest = "산책로 운영"
        final = "도서관 운영"
        self.run_cli("학습", uncertain, "개방", "이전 공지", "처음에는 개방으로 안내했다.")
        observations = (
            (final, "휴관", "도서관", "휴관 안내가 붙었다."),
            (strongest, "운영", "현장", "산책로 입구가 열렸다."),
            (strongest, "운영", "관리소", "운영을 공지했다."),
            (uncertain, "폐쇄", "이전 공지", "폐쇄로 공지가 정정됐다."),
        )

        output = self.learn_observations(*observations, continuous=True).stdout.splitlines()
        prefix = "선택한 학습 주제 — "
        topics = [line.removeprefix(prefix) for line in output if line.startswith(prefix)]
        self.assertEqual(topics, [uncertain, strongest, final])
        self.assertIn("학습할 새 관측이 없습니다", output[-1])
        self.assertIn("잠정 판단 — 폐쇄", self.run_cli("판단", uncertain).stdout)
        self.assertIn("운영 (출처 2개)", self.run_cli("판단", strongest).stdout)
        self.assertIn("잠정 판단 — 휴관", self.run_cli("판단", final).stdout)

        baseline = self.database.read_bytes()
        replay = self.learn_observations(*observations, continuous=True).stdout
        self.assertNotIn(prefix, replay)
        self.assertIn("학습할 새 관측이 없습니다", replay)
        self.assertEqual(self.database.read_bytes(), baseline)

    def test_autonomous_learning_extracts_claims_from_korean_text_records(self):
        document = self.workspace / "관측.TXT"
        document.write_text(
            "주제: 공원 운영\n출처: 관리소\n관측: 공원  운영은   중단입니다.\n\n"
            "주제: 공원 운영\n출처: 안내판\n관측: 공원 운영이 중단이다.\n\n"
            "주제: 도서관 위치\n출처: 지도\n관측: 도서관 위치는 중앙 광장입니다.\n\n"
            "주제: 도서관 위치\n출처: 운영기관\n관측: 도서관 위치가 중앙 광장이다.\n",
            encoding="utf-8",
        )
        self.run_cli("자율학습", "--자료", str(document), "--계속")
        self.assertIn("중단 (출처 2개)", self.run_cli("판단", "공원 운영").stdout)
        self.assertIn("중앙 광장 (출처 2개)", self.run_cli("판단", "도서관 위치").stdout)
        history = self.run_cli("기록", "공원 운영").stdout
        self.assertIn("중단 | 관리소 | 공원 운영은 중단입니다.", history)
        self.assertIn("중단 | 안내판 | 공원 운영이 중단이다.", history)
        history = self.run_cli("기록", "도서관 위치").stdout
        self.assertIn("중앙 광장 | 지도 | 도서관 위치는 중앙 광장입니다.", history)
        self.assertIn("중앙 광장 | 운영기관 | 도서관 위치가 중앙 광장이다.", history)

    def test_autonomous_learning_rejects_invalid_text_before_writing(self):
        document = self.workspace / "관측.txt"
        first_record = "주제: 공원 운영\n출처: 관리소\n관측: 공원 운영은 중단입니다.\n\n"
        second_header = "주제: 도서관 위치\n출처: 운영기관\n"
        self.run_cli("기록", "공원 운영")
        baseline = self.database.read_bytes()

        for invalid in (
            "설명: 도서관 위치는 중앙 광장입니다.",
            "관측: 도서관 위치를 중앙 광장으로 옮겨라.",
            "관측: 어린이 도서관 위치는 중앙 광장입니다.",
            "관측: 도서관 위치은 중앙 광장입니다.",
            "관측: 도서관 위치이 중앙 광장입니다.",
            "관측: 도서관 위치는 중앙 광장입니다. 공원은 동쪽입니다.",
        ):
            with self.subTest(invalid=invalid):
                document.write_text(first_record + second_header + invalid + "\n", encoding="utf-8")
                self.run_cli("자율학습", "--자료", str(document), "--계속", expected_status=None)
                self.assertEqual(self.database.read_bytes(), baseline)

    def test_autonomous_learning_merges_observations_from_json_and_text_files(self):
        topic = "공원 운영"
        json_document = self.write_observations((topic, "중단", "관리소", "정비 일정을 공지했다."))
        text_document = self.workspace / "현장.txt"
        text_document.write_text(
            "주제: 공원 운영\n출처: 현장 관찰\n관측: 공원 운영은 중단입니다.\n",
            encoding="utf-8",
        )

        result = self.run_cli("자율학습", "--자료", str(json_document), "--자료", str(text_document), "--계속")
        self.assertEqual(result.stdout.count(f"선택한 학습 주제 — {topic}"), 1)
        self.assertIn("중단 (출처 2개)", self.run_cli("판단", topic).stdout)
        history = self.run_cli("기록", topic).stdout
        self.assertIn("중단 | 관리소 | 정비 일정을 공지했다.", history)
        self.assertIn("중단 | 현장 관찰 | 공원 운영은 중단입니다.", history)

    def test_autonomous_learning_rejects_cross_file_conflicts_and_limit(self):
        topic = "공원 운영"
        text_document = self.workspace / "현장.txt"
        text_document.write_text(
            "주제: 공원 운영\n출처:  관리소 \n관측: 공원 운영은 중단입니다.\n",
            encoding="utf-8",
        )
        self.run_cli("기록", topic)
        baseline = self.database.read_bytes()
        cases = {
            "같은 출처의 충돌": [(topic, "개방", "관리소", "운영을 공지했다.")],
            "합산 항목 수 상한": [(topic, "중단", f"현장 {index}", "운영이 중단됐다.") for index in range(100)],
        }
        for label, observations in cases.items():
            with self.subTest(case=label):
                json_document = self.write_observations(*observations)
                self.run_cli(
                    "자율학습", "--자료", str(json_document), "--자료", str(text_document), "--계속",
                    expected_status=None,
                )
                self.assertEqual(self.database.read_bytes(), baseline)

    def test_autonomous_learning_ignores_historical_replay(self):
        topic = "관측소 운영"
        original = (topic, "운영", "관측소", "첫 일정에 운영으로 적혀 있었다.")
        revision = (topic, "중단", "관측소", "정정 일정에 중단으로 적혀 있었다.")
        self.learn_observations(original)
        self.learn_observations(revision)
        previous_history = self.run_cli("기록", topic).stdout
        self.assertIn(original[3], previous_history)
        self.assertIn(revision[3], previous_history)

        previous_database = self.database.read_bytes()
        self.learn_observations(original)
        self.assertEqual(self.database.read_bytes(), previous_database)
        self.assertEqual(self.run_cli("기록", topic).stdout, previous_history)
        self.assertIn("잠정 판단 — 중단", self.run_cli("판단", topic).stdout)

    def test_autonomous_learning_rejects_invalid_or_conflicting_batches(self):
        topic = "공원 운영"
        valid = (topic, "개방", "관리소", "운영을 공지했다.")
        invalid = (topic, "폐쇄", "현장", "   ")
        conflicting = (" 공원  운영 ", "폐쇄", " 관리소 ", "폐쇄를 공지했다.")
        too_many = [(topic, "개방", f"출처 {index}", "관측했다.") for index in range(101)]

        for data in ((valid, invalid), (valid, conflicting), too_many):
            with self.subTest(count=len(data), last_note=data[-1][3]):
                self.learn_observations(*data, expected_status=None)
                self.assertIn("저장된 증거가 없습니다", self.run_cli("기록", topic).stdout)

    def test_autonomous_learning_rolls_back_when_second_record_cannot_be_saved(self):
        topic = "공원 운영"
        self.run_cli("기록", topic)
        with sqlite3.connect(self.database) as connection:
            connection.execute("""
                CREATE TRIGGER reject_second_observation
                BEFORE INSERT ON evidence
                WHEN EXISTS (SELECT 1 FROM evidence WHERE topic = NEW.topic)
                BEGIN
                    SELECT RAISE(ABORT, 'second observation rejected');
                END
            """)
        failure = self.learn_observations(
            (topic, "개방", "관리소", "운영을 공지했다."),
            (topic, "개방", "현장", "출입문이 열려 있었다."),
            expected_status=None,
        )
        self.assertIn("second observation rejected", failure.stderr)
        self.assertIn("저장된 증거가 없습니다", self.run_cli("기록", topic).stdout)

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

    def test_verified_citation_integrates_only_matching_source_snapshot(self):
        topic = "공원 운영"
        self.run_cli("학습", topic, "개방", "현장 관찰", "첫 방문")
        document = self.database.with_name("공지.txt")
        original = "제목\n공원 운영은 야간에 중단된다.\n"
        document.write_text(original, encoding="utf-8")

        research = self.run_cli("탐구", "--자료", str(document)).stdout
        digest = research.split("파일 SHA-256 — ", 1)[1].strip()
        citation = ("인용학습", topic, "폐쇄", "관리소", str(document))
        wrong_line = self.run_cli(*citation, "1", digest, expected_status=1)
        self.assertIn("주제 문구를 찾지 못했습니다", wrong_line.stderr)

        document.write_text(original.replace("야간", "주간"), encoding="utf-8")
        stale = self.run_cli(*citation, "2", digest, expected_status=1)
        self.assertIn("SHA-256이 검색 결과와 다릅니다", stale.stderr)
        self.assertIn("잠정 판단 — 개방", self.run_cli("판단", topic).stdout)
        self.assertEqual(len(self.run_cli("기록", topic).stdout.splitlines()), 1)

        document.write_text(original, encoding="utf-8")
        saved = self.run_cli(*citation, "2", digest)
        self.assertIn("원본 검사 통과", saved.stdout)
        document.unlink()
        self.assertIn("판단 보류", self.run_cli("판단", topic).stdout)
        history = self.run_cli("기록", topic).stdout
        self.assertIn("공원 운영은 야간에 중단된다.", history)
        self.assertIn(f"줄 2, SHA-256 {digest}", history)
        self.assertIn("개방 | 현장 관찰", history)

    def test_citation_without_expected_hash_checks_current_document(self):
        topic = "공원 운영"
        document = self.database.with_name("공지.txt")
        data = "제목\n공원 운영은 야간에 중단된다.\n".encode("utf-8")
        document.write_bytes(data)
        citation = ("인용학습", topic, "폐쇄", "관리소", str(document))

        wrong_line = self.run_cli(*citation, "1", expected_status=1)
        self.assertIn("주제 문구를 찾지 못했습니다", wrong_line.stderr)
        self.assertIn("저장된 증거가 없습니다", self.run_cli("기록", topic).stdout)

        self.run_cli(*citation, "2")
        history = self.run_cli("기록", topic).stdout
        self.assertIn("공원 운영은 야간에 중단된다.", history)
        self.assertIn(f"줄 2, SHA-256 {hashlib.sha256(data).hexdigest()}", history)


if __name__ == "__main__":
    unittest.main()
