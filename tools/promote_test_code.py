"""Evaluate a TEST source snapshot, then publish only its code to CLEAN."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluate_learning import evaluate


ROOT = Path(__file__).resolve().parents[1]
TEST_SOURCE = ROOT / "selflearningai_test.py"
CLEAN_SOURCE = ROOT / "selflearningai_clean.py"
TEST_EDITION = b'\nEDITION = "TEST"\n'
CLEAN_EDITION = b'\nEDITION = "CLEAN"\n'


def promote(output_dir):
    source = TEST_SOURCE.read_bytes()
    if source.count(TEST_EDITION) != 1:
        raise ValueError("TEST 소스의 EDITION 선언을 확인하세요.")

    # 평가와 반영에 같은 소스 스냅샷을 사용한다.
    with TemporaryDirectory(dir=ROOT) as directory:
        staging = Path(directory)
        test_snapshot = staging / TEST_SOURCE.name
        test_snapshot.write_bytes(source)
        evaluate(output_dir, program=test_snapshot)

        clean_snapshot = staging / CLEAN_SOURCE.name
        clean_snapshot.write_bytes(source.replace(TEST_EDITION, CLEAN_EDITION, 1))
        clean_snapshot.chmod(CLEAN_SOURCE.stat().st_mode & 0o777)
        clean_snapshot.replace(CLEAN_SOURCE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path, help="새 TEST 평가 디렉터리")
    args = parser.parse_args()
    promote(args.output_dir.resolve())
    print(f"TEST 평가 통과. 코드만 CLEAN에 반영했습니다. 평가 기록: {args.output_dir}")


if __name__ == "__main__":
    main()
