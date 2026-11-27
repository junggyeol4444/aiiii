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
            line = " ".join(unicodedata.normalize("NFC", line).split())
            offset = line.find(topic)
            if offset == -1:
                continue
            start = max(0, offset - CONTEXT_CHARACTERS)
            end = offset + len(topic) + CONTEXT_CHARACTERS
            excerpt = line[start:end]
            if start:
                excerpt = "…" + excerpt
            if end < len(line):
                excerpt += "…"
            passages.append(Passage(path, number, display_text(excerpt), digest))
            matches += 1
            if matches == MAX_MATCHES_PER_DOCUMENT:
                break
    return passages
