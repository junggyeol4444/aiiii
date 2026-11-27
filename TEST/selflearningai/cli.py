import argparse
import sqlite3
from pathlib import Path

from .memory import CLEAN_DATABASE_NAME, Memory, normalize
from .observations import MAX_OBSERVATIONS, load_observations
from .research import display_text, find_passages, verify_passage


MAX_OBSERVATION_FILES = 8


def describe_claim(value, negated):
    return f"{value} 아님" if negated else value


def main(*, test_mode):
    edition = "TEST" if test_mode else "CLEAN"
    parser = argparse.ArgumentParser(description=f"SelfLearningAI {edition} 장기 기억과 탐구")
    if test_mode:
        parser.add_argument("--기억파일", dest="database", help="테스트용 기억 파일 경로")
    commands = parser.add_subparsers(dest="command", required=True)
    learn = commands.add_parser("학습", help="출처와 증거를 기억에 통합")
    for label in ("주제", "주장", "출처", "증거"):
        learn.add_argument(label)
    learn.add_argument("--부정", action="store_true", help="입력한 주장을 명시적으로 부정")
    verify = commands.add_parser("검증", help="저장된 지지와 명시적 반박을 대조")
    verify.add_argument("주제")
    verify.add_argument("주장")
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
    cite.add_argument("--부정", action="store_true", help="입력한 주장을 명시적으로 부정")
    automatic = commands.add_parser("자율학습", help="관측 자료에서 주제를 선택해 학습")
    automatic.add_argument(
        "--자료", dest="documents", action="append", required=True, metavar="파일",
        help="관측 파일을 지정합니다. 여러 번 사용할 수 있습니다.",
    )
    automatic.add_argument(
        "--계속", dest="continuous", action="store_true", help="자료에 남은 주제를 순서대로 학습",
    )
    args = parser.parse_args()
    program_dir = Path(__file__).resolve().parents[1]
    path = program_dir / CLEAN_DATABASE_NAME
    if test_mode:
        legacy = program_dir / "memory.sqlite3"
        default = program_dir / "test.sqlite3"
        path = args.database
        if path is None:
            path = legacy if not default.exists() and legacy.is_file() else default
    memory = Memory(path, test_mode=test_mode)
    try:
        if args.command == "자율학습":
            if len(args.documents) > MAX_OBSERVATION_FILES:
                raise ValueError(f"관측 파일은 한 번에 최대 {MAX_OBSERVATION_FILES}개까지 지정할 수 있습니다.")
            observations = []
            for document in args.documents:
                observations.extend(load_observations(document))
                if len(observations) > MAX_OBSERVATIONS:
                    raise ValueError(f"관측은 모든 자료를 합쳐 최대 {MAX_OBSERVATIONS}건까지 지정할 수 있습니다.")
            memory.initialize()
            while True:
                outcome = memory.learn_from_observations(observations)
                if outcome is None:
                    print("학습할 새 관측이 없습니다.")
                    return
                topic, count = outcome
                print(f"선택한 학습 주제 — {topic}")
                print(f"관측 {count}건을 통합하고 잠갔습니다.")
                if not args.continuous:
                    return
                observations = [record for record in observations if record[0] != topic]

        memory.initialize()
        if args.command == "학습":
            entry = memory.learn(args.주제, args.주장, args.출처, args.증거, negated=args.부정)
            print(f"검사 통과. 증거 {entry}번을 통합하고 잠갔습니다.")
        elif args.command == "인용학습":
            topic = normalize(args.주제, "주제", 200)
            passage = verify_passage(topic, args.파일, args.줄번호, args.sha256)
            note = (
                f"{passage.text} [파일 {str(passage.path)!r}, "
                f"줄 {passage.line_number}, SHA-256 {passage.sha256}]"
            )
            entry = memory.learn(topic, args.주장, args.출처, note, negated=args.부정)
            check = "원본 검사 통과" if args.sha256 is not None else "현재 파일의 인용 위치 확인"
            print(f"{check}. 증거 {entry}번을 통합하고 잠갔습니다.")
        elif args.command == "판단":
            results = memory.assess(args.주제)
            if not results:
                print("저장된 증거가 없습니다.")
            else:
                value, count, negated = results[0]
                if len(results) > 1 and results[1][1] == count:
                    print("판단 보류. 가장 많은 지지를 얻은 주장이 동률입니다.")
                else:
                    print(f"잠정 판단 — {describe_claim(value, negated)}")
                for value, count, negated in results:
                    print(f"- {describe_claim(value, negated)} (출처 {count}개)")
        elif args.command == "검증":
            claim = normalize(args.주장, "주장", 500)
            support, refutation, other = memory.verify_claim(args.주제, claim)
            print(f"검증 대상 — {claim}")
            print(f"지지 {support}건 · 명시적 반박 {refutation}건 · 다른 주장 {other}건")
        elif args.command == "탐구":
            candidate = memory.next_exploration()
            if candidate is None:
                print("현재 기억에서 추가 확인이 필요한 주제를 찾지 못했습니다.")
            else:
                (
                    topic, sources, leading, other, leading_votes, other_votes,
                    leading_negated, other_negated,
                ) = candidate
                leading = describe_claim(leading, leading_negated)
                if other is None:
                    reason = "현재 출처가 1개뿐입니다."
                    question = f"다른 출처에서도 ‘{leading}’ 주장을 뒷받침하나요?"
                else:
                    other = describe_claim(other, other_negated)
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
            for entry, value, source, note, timestamp, negated in records:
                claim = describe_claim(value, negated)
                print(f"{entry}. {claim} | {source} | {note} | {timestamp} UTC")
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"오류 — {error}\n")
