import argparse
import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    "run.py",
    "selflearningai/__init__.py",
    "selflearningai/cli.py",
    "selflearningai/memory.py",
    "selflearningai/research.py",
)
TEST_APPLICATION_ID = 0x534C4154  # "SLAT"
TEST_ARCHIVE = "SelfLearningAI-TEST.zip"
CLEAN_ARCHIVE = "SelfLearningAI-CLEAN.zip"


def evaluation_files(root):
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise ValueError(f"실제 평가 폴더를 지정해야 합니다 ({root}).")

    files = []
    directories = [root]
    while directories:
        directory = directories.pop()
        for path in directory.iterdir():
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                continue
            if (
                path.name.endswith((".", " "))
                or PureWindowsPath(path.name).is_reserved()
                or any(char in '\\:<>"|?*' or not char.isprintable() for char in path.name)
            ):
                raise ValueError(f"압축 파일에 사용할 수 없는 평가 경로입니다 ({path}).")
            if stat.S_ISDIR(mode):
                directories.append(path)
            elif stat.S_ISREG(mode):
                files.append(path.relative_to(root))
    if not files:
        raise ValueError(f"평가 폴더에 포함할 일반 파일이 없습니다 ({root}).")
    return sorted(files)


def snapshot_test_database(source_path, snapshot_path):
    if not source_path.is_file():
        raise ValueError(f"테스트 기억 파일이 필요합니다 ({source_path}).")
    source_uri = source_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as source:
        with closing(sqlite3.connect(snapshot_path)) as snapshot:
            source.backup(snapshot)
            application_id = snapshot.execute("PRAGMA application_id").fetchone()[0]
            version = snapshot.execute("PRAGMA user_version").fetchone()[0]
            if application_id != TEST_APPLICATION_ID or version != 1:
                raise ValueError(f"지원하는 SelfLearningAI 테스트 기억 파일이 필요합니다 ({source_path}).")
            if snapshot.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError(f"테스트 기억 파일 무결성 검사에 실패했습니다 ({source_path}).")
            snapshot.execute(
                "SELECT id, topic, value, source, note, recorded_at FROM evidence LIMIT 0"
            )
            snapshot.execute("PRAGMA journal_mode = DELETE")


def read_distribution_file(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"배포에 필요한 파일을 읽을 수 없습니다 ({path}).")
    return path.read_bytes()


def read_edition_files(edition, readme):
    root = ROOT / edition
    for directory in (root, root / "selflearningai"):
        if not stat.S_ISDIR(directory.lstat().st_mode):
            raise ValueError(f"실제 프로그램 폴더가 필요합니다 ({directory}).")
    files = {f"{edition}/README.md": readme}
    for name in RUNTIME_FILES:
        files[f"{edition}/{name}"] = read_distribution_file(root / name)
    return files


def build_distributions(test_db, evaluation_dir, output_dir):
    evaluations = evaluation_files(evaluation_dir)
    readme = read_distribution_file(ROOT / "README.md")
    test_files = read_edition_files("TEST", readme)
    clean_files = read_edition_files("CLEAN", readme)
    output_dir.mkdir(parents=True, exist_ok=True)
    destinations = [output_dir / name for name in (TEST_ARCHIVE, CLEAN_ARCHIVE)]
    for destination in destinations:
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"기존 배포 파일이 있습니다 ({destination}).")

    with TemporaryDirectory(dir=output_dir) as temporary_directory:
        temporary = Path(temporary_directory)
        snapshot = temporary / "test.sqlite3"
        snapshot_test_database(test_db, snapshot)
        with ZipFile(temporary / TEST_ARCHIVE, "w", ZIP_DEFLATED, strict_timestamps=False) as archive:
            for name, data in test_files.items():
                archive.writestr(name, data)
            archive.write(snapshot, "TEST/test.sqlite3")
            for relative in evaluations:
                source = evaluation_dir / relative
                if not stat.S_ISREG(source.lstat().st_mode):
                    raise ValueError(f"평가 파일이 생성 중 변경되었습니다 ({source}).")
                archive.write(source, (Path("TEST/evaluation") / relative).as_posix())
        with ZipFile(temporary / CLEAN_ARCHIVE, "w", ZIP_DEFLATED, strict_timestamps=False) as archive:
            for name, data in clean_files.items():
                archive.writestr(name, data)
        os.link(temporary / TEST_ARCHIVE, destinations[0])
        try:
            os.link(temporary / CLEAN_ARCHIVE, destinations[1])
        except OSError:
            destinations[0].unlink()
            raise
    return destinations


def main():
    parser = argparse.ArgumentParser(description="SelfLearningAI 테스트·클린 배포 파일 생성")
    parser.add_argument("--test-db", required=True, type=Path, help="테스트 기억 SQLite 파일")
    parser.add_argument("--evaluation-dir", required=True, type=Path, help="평가 자료 폴더")
    parser.add_argument("--output-dir", required=True, type=Path, help="배포 ZIP을 저장할 폴더")
    args = parser.parse_args()
    try:
        destinations = build_distributions(args.test_db, args.evaluation_dir, args.output_dir)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"배포 파일 생성 오류 — {error}\n")
    for destination in destinations:
        print(destination)


if __name__ == "__main__":
    main()
