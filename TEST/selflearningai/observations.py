import json
import re
from itertools import groupby
from pathlib import Path

from .memory import normalize
from .research import read_document


FIELDS = {"주제": 200, "주장": 500, "출처": 500, "증거": 4000}
MAX_OBSERVATIONS = 100
TEXT_LABELS = ("주제", "출처", "관측")
TOPIC_REFERENCES = ("이 주제", "그 주제", "해당 주제")
TEXT_PREDICATE = re.compile(r"([은는이가]) (\S(?:.*\S)?)(?:이다|입니다)\.?")
CLAUSE_BOUNDARY = re.compile(r"[.!?…](?: |$)")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"중복된 항목입니다 ({key!r}).")
        result[key] = value
    return result


def _normalize_field(value, field, location):
    if not isinstance(value, str):
        raise ValueError(f"{location}의 {field}은(는) 문자열이어야 합니다.")
    try:
        value = normalize(value, field, FIELDS[field])
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{location}의 {field}에 잘못된 유니코드 문자가 있습니다.") from error
    except ValueError as error:
        raise ValueError(f"{location}. {error}") from error
    return value


def _parse_json_observations(content, path):
    try:
        records = json.loads(content, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise ValueError(f"관측 JSON을 읽을 수 없습니다 ({path}). {error}") from error
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_OBSERVATIONS:
        raise ValueError(f"관측 JSON은 항목이 1~{MAX_OBSERVATIONS}개인 배열이어야 합니다 ({path}).")

    observations = []
    for index, record in enumerate(records, start=1):
        location = f"{path}의 관측 {index}번"
        if not isinstance(record, dict) or record.keys() != FIELDS.keys():
            raise ValueError(f"{location}에 주제, 주장, 출처, 증거가 각각 필요합니다.")
        observations.append(tuple(_normalize_field(record[field], field, location) for field in FIELDS))
    return observations


def _parse_text_record(lines, location, previous_topic):
    fields = [line.strip().partition(":") for line in lines]
    labels = tuple(label for label, _, _ in fields)
    if any(not separator for _, separator, _ in fields) or labels not in (TEXT_LABELS, TEXT_LABELS[1:]):
        raise ValueError(f"{location}에 주제, 출처, 관측 줄이 이 순서대로 필요합니다.")
    source = _normalize_field(fields[-2][2], "출처", location)
    sentence = _normalize_field(fields[-1][2], "증거", location)
    if labels == TEXT_LABELS:
        topic = _normalize_field(fields[0][2], "주제", location)
        subject = topic
    else:
        if previous_topic is None:
            raise ValueError(f"{location}의 관측이 참조할 앞 주제가 같은 파일에 없습니다.")
        topic = previous_topic
        subject = next((name for name in TOPIC_REFERENCES if sentence.startswith(name)), None)
        if subject is None:
            raise ValueError(f"{location}에서 주제 줄을 생략할 때는 ‘이 주제’, ‘그 주제’ 또는 ‘해당 주제’를 쓰세요.")
    if not sentence.startswith(subject):
        raise ValueError(f"{location}의 관측 문장이 주제와 일치하지 않습니다.")
    predicate = TEXT_PREDICATE.fullmatch(sentence[len(subject):])
    if predicate is None:
        raise ValueError(f"{location}의 관측 문장은 주제와 조사 뒤에 주장과 ‘이다’ 또는 ‘입니다’가 필요합니다.")
    particle, claim = predicate.groups()
    last_character = ord(subject[-1])
    if 0xAC00 <= last_character <= 0xD7A3:
        has_final_consonant = (last_character - 0xAC00) % 28 != 0
        expected_particles = "은이" if has_final_consonant else "는가"
        if particle not in expected_particles:
            raise ValueError(f"{location}의 관측 문장에서 주제의 받침에 맞는 조사를 사용하세요.")
    if CLAUSE_BOUNDARY.search(claim):
        raise ValueError(f"{location}에는 관측 문장을 하나만 입력하세요.")
    claim = _normalize_field(claim, "주장", location)
    return topic, claim, source, sentence


def _parse_text_observations(content, path):
    observations = []
    previous_topic = None
    blocks = groupby(content.splitlines(), key=lambda line: bool(line.strip()))
    for nonblank, lines in blocks:
        if not nonblank:
            continue
        if len(observations) == MAX_OBSERVATIONS:
            raise ValueError(f"관측 텍스트에는 최대 {MAX_OBSERVATIONS}개를 입력할 수 있습니다 ({path}).")
        location = f"{path}의 관측 {len(observations) + 1}번"
        record = _parse_text_record(lines, location, previous_topic)
        observations.append(record)
        previous_topic = record[0]
    if not observations:
        raise ValueError(f"관측 텍스트에 최소 1개의 관측이 필요합니다 ({path}).")
    return observations


def load_observations(path):
    path = Path(path)
    content, _ = read_document(path)
    if path.suffix.casefold() == ".txt":
        return _parse_text_observations(content, path)
    return _parse_json_observations(content, path)
