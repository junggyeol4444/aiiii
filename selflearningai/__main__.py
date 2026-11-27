import argparse
import sqlite3

from .memory import Memory
from .research import display_text, find_passages


def main():
    parser = argparse.ArgumentParser(description="SelfLearningAI 장기 기억과 탐구")
    parser.add_argument("--기억파일", dest="database", default="memory.sqlite3")
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
    args = parser.parse_args()
    memory = Memory(args.database)
    try:
        memory.initialize()
        if args.command == "학습":
            entry = memory.learn(args.주제, args.주장, args.출처, args.증거)
            print(f"검사 통과. 증거 {entry}번을 통합하고 잠갔습니다.")
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
