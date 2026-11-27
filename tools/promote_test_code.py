"""Evaluate a TEST project snapshot and promote only its Python modules."""

import argparse
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluate_learning import evaluate


ROOT = Path(__file__).resolve().parents[1]
TEST_PROJECT = ROOT / "TEST"
CLEAN_PROJECT = ROOT / "CLEAN"
PACKAGE_NAME = "selflearningai"


def snapshot_test_project(snapshot):
    source_package = TEST_PROJECT / PACKAGE_NAME
    snapshot.mkdir()
    shutil.copyfile(TEST_PROJECT / "run.py", snapshot / "run.py")
    for source in sorted(source_package.rglob("*.py")):
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"일반 Python 소스 파일이 필요합니다: {source}")
        destination = snapshot / PACKAGE_NAME / source.relative_to(source_package)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def promote(output_dir):
    with TemporaryDirectory(prefix=".promotion-", dir=ROOT) as directory:
        staging = Path(directory)
        snapshot = staging / "TEST"
        snapshot_test_project(snapshot)
        evaluate(output_dir, program=snapshot / "run.py")

        clean_package = CLEAN_PROJECT / PACKAGE_NAME
        backup = staging / "previous"
        had_package = clean_package.exists()
        if had_package:
            clean_package.rename(backup)
        try:
            (snapshot / PACKAGE_NAME).rename(clean_package)
        except OSError:
            if had_package:
                backup.rename(clean_package)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path, help="새 TEST 평가 디렉터리")
    args = parser.parse_args()
    promote(args.output_dir.resolve())
    print(f"TEST 평가 통과. 검증한 모듈을 CLEAN에 반영했습니다. 평가 기록: {args.output_dir}")


if __name__ == "__main__":
    main()
