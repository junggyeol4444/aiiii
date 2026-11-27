# SelfLearningAI

한국어로 사용하는 독립 프로그램입니다. 첫 개발 분야는 장기 기억과 증거에 따른 판단 갱신입니다. Python 3.10 이상과 표준 라이브러리만 사용합니다.

## 실행

SelfLearningAI의 개발 목표는 스스로 학습하고 이해하며 판단을 갱신하는 기본 지능입니다. 현재 구현 범위는 장기 기억, 증거에 따른 잠정 판단, 기억을 바탕으로 한 탐구입니다.

### TEST와 CLEAN

| 구분 | TEST | CLEAN |
| --- | --- | --- |
| 실행 파일 | `selflearningai_test.py` | `selflearningai_clean.py` |
| 코드 | 이 파일에서 개발 | 통과한 TEST 코드를 이 파일에 반영 |
| 배포 시 기억 | 개발 중 얻은 지식·기억·경험 포함 | 빈 상태에서 시작 |
| 평가 자료와 결과 | 포함 | 제외 |
| 제공 후 학습 | 가능 | 가능 |

각 Python 파일은 장기 기억, 판단, 탐구, 학습 코드를 모두 포함합니다. 사용할 파일 하나만 별도 디렉터리에 두고 Python으로 실행할 수 있습니다. CLEAN 실행 파일은 `clean.sqlite3`만 사용하며 처음 실행할 때 빈 기억을 만듭니다. TEST 기억 파일을 `clean.sqlite3`로 복사하거나 이름을 바꿔도 SQLite 내부의 종류 표시를 검사해 열기를 거부합니다.

TEST 실행 파일은 `test.sqlite3`를 사용합니다. `test.sqlite3`가 없으면 이전 버전의 `memory.sqlite3`를 TEST에서 이어서 사용합니다. 별도 TEST 기억 경로가 필요하면 TEST 실행 파일의 `--기억파일 경로`를 사용합니다.

```bash
python3 selflearningai_test.py 기록 "가상 관측소의 야간 운영"
python3 selflearningai_clean.py 학습 "공원의 야간 개방" "개방" "현장 관찰" "출입문이 열려 있었다."
python3 selflearningai_clean.py 판단 "공원의 야간 개방"
```

## 검사와 판단

입력의 공백과 유니코드를 정규화하고 필수 항목, 길이, 제어 문자, 같은 주제에서 출처의 최신 기록과 동일한 입력을 검사합니다. 통과한 증거는 SQLite 트랜잭션으로 저장합니다. SQLite 트리거가 행의 일반적인 수정과 삭제를 차단합니다. 파일과 스키마에 직접 접근할 수 있는 사람에 대한 변조 방지는 운영체제 권한에 의존합니다.

같은 출처의 보완과 정정은 새 기록으로 저장합니다. 판단에는 주제별로 각 출처의 최신 기록만 반영하고, 가장 많이 지지받은 주장을 잠정 판단으로 표시합니다. 동률이면 보류합니다. 기존 주장을 지지한 기록은 이후 판단이 바뀌어도 조회할 수 있습니다. 주제와 주장의 비교는 정규화된 문자열 기준입니다. 입력은 현재 사람이 제공하며 증거의 진위나 출처 간 독립성은 판단하지 않습니다.

## 다음 탐구 주제 선택

```bash
python3 selflearningai_test.py 탐구
```

기억에 있는 주제를 검토해 가장 많은 지지를 받은 주장이 동률인 주제, 의견이 갈리는 주제, 출처가 한 곳뿐인 주제 순서로 선택합니다. 의견이 갈리는 주제끼리는 상위 두 주장 간 출처 수 차이가 작은 주제를 먼저 확인합니다. 우선순위가 같으면 최근에 증거가 추가된 주제를 먼저 선택합니다. 선택 이유와 확인할 질문을 출력합니다. 탐구 주제는 기억에서 선택합니다. 선택한 주제를 로컬 자료에서 조사하려면 자료 파일을 지정합니다.

```bash
python3 selflearningai_test.py 탐구 --자료 운영.txt --자료 관측.txt
```

각 UTF-8 파일에서 주제 문구가 나오는 줄을 최대 3개씩 찾습니다. 비교할 때 유니코드와 공백을 정규화합니다. 파일당 최대 1 MiB를 읽으며 후보마다 파일 경로, 줄 번호, 구절, 원본 파일의 SHA-256을 표시합니다. 후보는 판단을 위한 검토 자료이며, 진위나 지지 여부를 자동 판정하거나 기억에 자동 등록하지 않습니다.

## 확인한 인용을 기억에 통합

```bash
python3 selflearningai_test.py 인용학습 "공원의 야간 개방" "폐쇄" "관리소" 운영.txt 2
```

프로그램은 지정한 줄에 주제 문구가 있는지 확인합니다. 검사를 통과하면 인용문과 파일 경로, 줄 번호, 현재 파일의 SHA-256을 증거에 함께 저장합니다. 사용자가 주장과 출처를 지정하며 같은 출처의 이름을 일관되게 써야 정정으로 집계됩니다.

탐구 때와 파일 내용이 바이트 단위로 같은지 확인해야 할 때는 줄 번호 뒤에 탐구 결과의 SHA-256을 붙입니다. 생략하면 등록 시점의 파일을 기준으로 검사합니다. 인용문이 주장을 뒷받침하는지와 출처의 신뢰성은 사용자가 판단합니다.

## 통합 테스트

```bash
python3 -m unittest discover -s tests -v
```

실제 CLI를 여러 프로세스에서 실행해 기억 유지, 판단 보류와 변경, 기존 증거 보존, 입력 검사, 출처 정정, 이전 형식 기억 파일의 자동 변환, 클린과 테스트의 격리, 선택적 인용 해시 확인, 데이터베이스 잠금을 확인합니다.

## TEST에서 개발하고 CLEAN에 반영

1. 개발 코드는 `selflearningai_test.py`에서 수정합니다. 개발 중 학습은 이 파일로 실행하고 TEST의 기억과 평가 자료를 보존합니다.
2. TEST 전용 통합 테스트를 먼저 실행합니다.
3. `promote_test_code.py`는 TEST 코드 스냅샷으로 별도의 학습·평가를 실행합니다. 통과하면 같은 스냅샷의 코드만 `selflearningai_clean.py`에 반영합니다. 실패하면 기존 CLEAN 코드가 유지됩니다. 평가 디렉터리는 새 경로를 지정합니다.
4. 두 프로그램이 각각 실행되는지 통합 테스트로 확인하고 두 배포본을 만듭니다.

```bash
python3 -m unittest discover -s tests -p test_integration.py -k TestProgramIntegrationTest
python3 tools/promote_test_code.py --output-dir evaluation-run
python3 -m unittest discover -s tests -v
python3 tools/build_distributions.py --test-db evaluation-run/test.sqlite3 --evaluation-dir evaluation-run/evaluation --output-dir dist
```

배포 도구는 각 ZIP에 해당 소스 파일을 그대로 넣습니다. TEST ZIP에는 그 버전의 TEST 기억과 평가 자료도 포함합니다. CLEAN ZIP에는 프로그램 파일과 README가 들어갑니다. 개발 중 축적한 별도의 TEST 기억을 제공하려면 배포 도구에 해당 기억 파일과 평가 디렉터리를 지정합니다.
