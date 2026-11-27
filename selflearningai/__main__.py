import argparse
import sqlite3

from .memory import Memory


def main():
    parser = argparse.ArgumentParser(description="SelfLearningAI 장기 기억")
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
        else:
            records = memory.history(args.주제)
            if not records:
                print("저장된 증거가 없습니다.")
            for entry, value, source, note, timestamp in records:
                print(f"{entry}. {value} | {source} | {note} | {timestamp} UTC")
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f"오류 — {error}\n")


if __name__ == "__main__":
    main()
