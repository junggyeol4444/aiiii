import json
from pathlib import Path

from .memory import normalize
from .research import read_document


FIELDS = {"주제": 200, "주장": 500, "출처": 500, "증거": 4000}
MAX_OBSERVATIONS = 100


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"중복된 항목입니다 ({key!r}).")
        result[key] = value
    return result


def load_observations(path):
    path = Path(path)
    content, _ = read_document(path)
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
        values = []
        for field, limit in FIELDS.items():
            value = record[field]
            if not isinstance(value, str):
                raise ValueError(f"{location}의 {field}은(는) 문자열이어야 합니다.")
            try:
                value = normalize(value, field, limit)
                value.encode("utf-8")
            except UnicodeEncodeError as error:
                raise ValueError(f"{location}의 {field}에 잘못된 유니코드 문자가 있습니다.") from error
            except ValueError as error:
                raise ValueError(f"{location}. {error}") from error
            values.append(value)
        observations.append(tuple(values))
    return observations
