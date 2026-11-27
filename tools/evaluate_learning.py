"""Run a documented learning scenario in a fresh TEST workspace."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from contextlib import closing


ROOT = Path(__file__).resolve().parents[1]
TOPIC = "가상 관측소의 야간 운영"


def evaluate(directory):
    directory.mkdir()
    evaluation = directory / "evaluation"
    evaluation.mkdir()
    document = evaluation / "운영 공지.txt"
    document.write_text(f"{TOPIC}은 중단됐습니다.\n", encoding="utf-8")
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    document_argument = str(document.relative_to(directory))
    database = directory / "test.sqlite3"
    environment = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    steps = [
        (("학습", TOPIC, "운영", "예전 공지", "야간 운영이 예고됐습니다."), "증거 1번"),
        (("판단", TOPIC), "잠정 판단 — 운영"),
        (("탐구", "--자료", document_argument), f"파일 SHA-256 — {digest}"),
        (("인용학습", TOPIC, "중단", "새 공지", document_argument, "1", digest), "증거 2번"),
        (("판단", TOPIC), "판단 보류"),
        (("학습", TOPIC, "중단", "현장 확인", "관측소 출입구가 닫혀 있었습니다."), "증거 3번"),
        (("판단", TOPIC), "잠정 판단 — 중단"),
        (("기록", TOPIC), "운영 | 예전 공지 | 야간 운영이 예고됐습니다."),
    ]
    (evaluation / "시나리오.json").write_text(
        json.dumps(
            {
                "설명": "합성 자료로 탐구, 인용 검사, 판단 갱신, 과거 기록 보존을 검증합니다.",
                "단계": [{"명령": arguments, "기대 출력": expected} for arguments, expected in steps],
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    results = []
    for arguments, expected in steps:
        result = subprocess.run(
            [sys.executable, "-m", "selflearningai", "--모드", "테스트", *arguments],
            cwd=directory,
            env=environment,
            capture_output=True,
            encoding="utf-8",
            timeout=15,
            check=True,
        )
        if expected not in result.stdout:
            raise RuntimeError(f"{arguments[0]} 결과에 기대 출력이 없습니다: {result.stdout}")
        results.append({"명령": arguments[0], "출력": result.stdout.rstrip()})

    with closing(sqlite3.connect(database)) as connection:
        try:
            connection.execute("UPDATE evidence SET note = '수정 시도' WHERE id = 1")
        except sqlite3.IntegrityError as error:
            if "잠긴 증거" not in str(error):
                raise
        else:
            raise RuntimeError("잠긴 증거를 수정할 수 있었습니다.")
    results.append({"검사": "잠긴 증거 수정 차단", "결과": "통과"})
    (evaluation / "결과.json").write_text(
        json.dumps({"결과": "통과", "단계": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path, help="새 TEST 평가 디렉터리")
    args = parser.parse_args()
    evaluate(args.output_dir.resolve())
    print(f"TEST 평가 통과 — {args.output_dir}")


if __name__ == "__main__":
    main()
