import hashlib
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path


MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_MATCHES_PER_DOCUMENT = 3
CONTEXT_CHARACTERS = 80


@dataclass(frozen=True)
class Passage:
    path: Path
    line_number: int
    text: str
    sha256: str


def read_document(path):
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"일반 파일을 지정해야 합니다: {path}")
    with path.open("rb") as stream:
        data = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError(f"문서는 1 MiB 이하여야 합니다: {path}")
    try:
        return data.decode("utf-8-sig"), hashlib.sha256(data).hexdigest()
    except UnicodeDecodeError as error:
        raise ValueError(f"UTF-8 문서를 지정해야 합니다: {path}") from error


def display_text(text):
    return "".join(character if character.isprintable() else "�" for character in text)


def matching_excerpt(topic, line):
    line = " ".join(unicodedata.normalize("NFC", line).split())
    offset = line.find(topic)
    if offset == -1:
        return None
    start = max(0, offset - CONTEXT_CHARACTERS)
    end = offset + len(topic) + CONTEXT_CHARACTERS
    excerpt = line[start:end]
    if start:
        excerpt = "…" + excerpt
    if end < len(line):
        excerpt += "…"
    return display_text(excerpt)


def verify_passage(topic, document, line_number, expected_digest):
    if len(expected_digest) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in expected_digest
    ):
        raise ValueError("검색 결과에 표시된 64자리 SHA-256을 입력해야 합니다.")
    path = Path(document).resolve()
    content, digest = read_document(path)
    if digest != expected_digest.lower():
        raise ValueError("파일 SHA-256이 검색 결과와 다릅니다. 다시 탐구하세요.")
    lines = content.splitlines()
    if not 1 <= line_number <= len(lines):
        raise ValueError("자료에 해당 줄 번호가 없습니다.")
    excerpt = matching_excerpt(topic, lines[line_number - 1])
    if excerpt is None:
        raise ValueError("지정한 줄에서 주제 문구를 찾지 못했습니다.")
    return Passage(path, line_number, excerpt, digest)


def find_passages(topic, documents):
    passages = []
    seen = set()
    for document in documents:
        path = Path(document).resolve()
        if path in seen:
            continue
        seen.add(path)
        content, digest = read_document(path)
        matches = 0
        for number, line in enumerate(content.splitlines(), start=1):
            excerpt = matching_excerpt(topic, line)
            if excerpt is None:
                continue
            passages.append(Passage(path, number, excerpt, digest))
            matches += 1
            if matches == MAX_MATCHES_PER_DOCUMENT:
                break
    return passages
