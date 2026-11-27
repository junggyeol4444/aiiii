"""Run a documented learning scenario in a fresh TEST workspace."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from contextlib import closing


ROOT = Path(__file__).resolve().parents[1]
TOPIC = "가상 관측소의 야간 운영"


def evaluate(directory, *, program=ROOT / "TEST" / "run.py"):
    directory.mkdir()
    evaluation = directory / "evaluation"
    evaluation.mkdir()
    document = evaluation / "운영 공지.txt"
    document.write_text(f"{TOPIC}은 중단됐습니다.\n", encoding="utf-8")
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    document_argument = str(document.relative_to(directory))
    observation_file = evaluation / "관측 기록.json"
    next_topic = "가상 실험실의 주간 운영"
    observations = [
        (TOPIC, "중단", "관측 기록실", "야간 장비가 꺼져 있었습니다."),
        (next_topic, "운영", "시설 안내", "주간 운영 시간이 공지됐습니다."),
        (next_topic, "운영", "방문 기록", "주간에 출입할 수 있었습니다."),
    ]
    observation_file.write_text(
        json.dumps(
            [dict(zip(("주제", "주장", "출처", "증거"), record)) for record in observations],
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    automatic = ("자율학습", "--자료", str(observation_file.relative_to(directory)))
    text_topic = "가상 도서실"
    text_observation = evaluation / "도서실 관측.txt"
    text_observation.write_text(
        f"주제: {text_topic}\n출처: 안내문\n관측: {text_topic}은 개방입니다.\n"
        "\n출처: 방문자 기록\n관측: 그 주제는 개방입니다.\n"
        "\n출처: 시설 기록\n관측: 그 주제는 개방이 아닙니다.\n",
        encoding="utf-8",
    )
    text_argument = str(text_observation.relative_to(directory))
    relations = evaluation / "개념 관측.txt"
    relations.write_text(
        "주제: 참새\n출처: 표본 카드\n관측: 참새는 새의 한 종류입니다.\n"
        "\n주제: 새\n출처: 분류 기록\n관측: 새는 동물의 한 종류입니다.\n"
        "\n주제: 날개\n출처: 모형 설명\n관측: 날개는 새의 일부입니다.\n",
        encoding="utf-8",
    )
    relation_argument = str(relations.relative_to(directory))
    database = directory / "test.sqlite3"
    steps = [
        (("학습", TOPIC, "운영", "예전 공지", "야간 운영이 예고됐습니다."), "증거 1번"),
        (("판단", TOPIC), "잠정 판단 — 운영"),
        (("탐구", "--자료", document_argument), f"파일 SHA-256 — {digest}"),
        (("인용학습", TOPIC, "중단", "새 공지", document_argument, "1", digest), "증거 2번"),
        (("판단", TOPIC), "판단 보류"),
        (("학습", TOPIC, "중단", "현장 확인", "관측소 출입구가 닫혀 있었습니다."), "증거 3번"),
        (("판단", TOPIC), "잠정 판단 — 중단"),
        (("기록", TOPIC), "운영 | 예전 공지 | 야간 운영이 예고됐습니다."),
        ((*automatic, "--자료", text_argument, "--계속"), "학습할 새 관측이 없습니다."),
        (("판단", TOPIC), "중단 (출처 3개)"),
        (("판단", next_topic), "운영 (출처 2개)"),
        (automatic, "학습할 새 관측이 없습니다."),
        (("기록", text_topic), "개방 | 방문자 기록 | 그 주제는 개방입니다."),
        (("검증", text_topic, "개방"), "지지 2건 · 명시적 반박 1건 · 다른 주장 0건"),
        (("기록", text_topic), "개방 아님 | 시설 기록 | 그 주제는 개방이 아닙니다."),
        (("자율학습", "--자료", relation_argument, "--계속"), "학습할 새 관측이 없습니다."),
        (("개념", "참새"), "종류 → 새 (지지 1건 · 명시적 반박 0건)"),
        (("관계", "참새", "종류", "동물"), "추론 경로 — 참새 → 새 → 동물"),
        (("관계", "날개", "부분", "새"), "직접 근거 — 날개 → 새"),
        (("관계", "날개", "부분", "동물"), "관계 근거가 부족합니다"),
    ]
    (evaluation / "시나리오.json").write_text(
        json.dumps(
            {
                "설명": "합성 자료로 탐구, 인용 검사, 판단 갱신, 과거 기록 보존과 자율학습을 검증합니다.",
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
            [
                sys.executable, "-E", "-s", "-S", "-B", "-X", "utf8", str(program),
                "--기억파일", str(database), *arguments,
            ],
            cwd=directory,
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
