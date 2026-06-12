# K. TEST 자동화 — 구조 문서

`K. TEST 자동화.py` 가 무엇을 하고, `Z:\home\Drive\TEST 및 답지\일괄출력\TEST 자동화\` 의 파일들이 왜 필요한지 정리.

## 한 줄 요약

**K 는 GUI 런처일 뿐, 실제 로직은 `TEST 자동화/` 폴더의 .py 들이 담당.** 둘 다 있어야 동작함.

## 디렉터리 구조

```
Z:\home\Drive\문서 자동화 작업\완성(코드)\
   ├─ K. TEST 자동화.py        ← 이 런처 GUI
   └─ K. TEST 자동화.md        ← 이 문서
            │
            │ subprocess.Popen([python, script_path], cwd=TEST_AUTO_DIR, env=...)
            ↓
Z:\home\Drive\TEST 및 답지\일괄출력\TEST 자동화\
   ├─ 진행률체크.py            ← K 수업준비 ① 호출
   ├─ 구글연동.py              ← K 수업준비 ② 첫째 단계 (체인)
   ├─ 단어관리자료업뎃.py      ← K 수업준비 ② 둘째 단계 (체인)
   ├─ 개별단어장생성.py        ← K 수업준비 ③ 호출
   ├─ 내신TEST출력.py          ← K 수업준비 ④ 호출
   ├─ 모고엑셀답지생성.py      ← K 모의고사 답지 ① 호출
   ├─ 학생별오답.py            ← K 모의고사 답지 ② 호출 (단계 1·2·3·4 옵션)
   ├─ 모고배정추출.py          ← K 모의고사 답지 ③ 호출
   ├─ 엑셀답지생성.py          ← K 내신 답지 첫째 호출
   ├─ 엑셀답지업데이트.py      ← K 내신 답지 둘째 호출
   ├─ PDF책스캔.py             ← K 버튼 제거됨. 책범위.xlsx 갱신 필요시 직접 실행
   ├─ _extract_session.py      ← Google 세션 보조 (드물게 사용)
   ├─ credentials.json / client_secret.json / authorized_user.json
   │                           ← Google Drive·Sheets API 인증
   ├─ 단어관리자료.xlsx        ← 데이터 (단어관리자료업뎃이 갱신)
   ├─ 교재목록.xlsx            ← 보조 (안 쓸 수도 있음)
   ├─ 모고정답입력/            ← 모의고사 DB·산출물
   │   ├─ 고1/고2/고3 모의고사 db ...xlsx     ← 정답 DB
   │   ├─ 책범위.xlsx                          ← PDF책스캔.py 산출물
   │   ├─ 학생별모고배정.xlsx                  ← 모고배정추출.py 산출물
   │   └─ 학생오답xlsx/                        ← 학생별오답.py 산출물
   │       └─ 한글출력/                         ← 단계 3 hwp/pdf, 단계 4 인쇄 대상
   ├─ 내신TEST/ / 양식/ / 학생별/ / 단어/ / 어법/ / 요약문완성/
   │                           ← 카테고리별 템플릿·산출물
   └─ PDF/                     ← 개별단어장생성 등 PDF 산출물

Z:\home\Drive\TEST 및 답지\일괄출력\
   ├─ 0. 학생관리자료.xlsx     ← 마스터 데이터 (모든 스크립트가 ../로 참조)
   ├─ 0. 채점용 답지/
   ├─ 내신정답입력/ / 내신단어영작/ / 어법TEST모음/ ...
   └─ ...
```

## K 가 호출하는 방식

```python
TEST_AUTO_DIR = r"Z:\home\Drive\TEST 및 답지\일괄출력\TEST 자동화"

subprocess.Popen(
    [PYTHON_EXE, "-u", os.path.join(TEST_AUTO_DIR, script_filename)],
    cwd=TEST_AUTO_DIR,           # 스크립트가 자기 폴더 기준으로 동작
    stdout=PIPE, stderr=STDOUT,
    env={**os.environ, "PYTHONIOENCODING": "utf-8", **env_override},
)
```

K 가 환경변수로 옵션 주입:
- `PEDU_FILTER_STUDENT` — 학생 이름 필터 (모고엑셀답지생성, 학생별오답, 진행률체크)
- `PEDU_STEPS_TO_RUN` — 학생별오답 실행 단계 ('1,2,3' / '4' 등)
- `PEDU_OVERRIDE_BOOK_NAME` / `PEDU_OVERRIDE_STUDENT` / `PEDU_OVERRIDE_START` / `PEDU_OVERRIDE_END`
   — 개별단어장생성 단일행 오버라이드
- `PEDU_WARN_THRESHOLD` — 진행률체크 경고 임계값 (기본 3)

## 왜 K 로 합치지 않고 따로 두나

각 스크립트가 **자기 폴더 기준 상대경로**에 강하게 의존:
- `BASE = os.path.dirname(os.path.abspath(__file__))`
- `STUDENT_DATA_FILE = os.path.normpath(os.path.join(BASE, '..', '0. 학생관리자료.xlsx'))`
- `credentials.json`, `client_secret.json` 등 같은 폴더 참조
- `모고정답입력/`, `내신TEST/` 등 같은 폴더 하위 디렉터리 사용

→ K 폴더로 옮기거나 코드 합치면 모든 경로가 깨짐. 의도적으로 **K = 얇은 GUI wrapper**, 본체는 그대로 둠.

## 삭제 가능 여부

| 항목 | 삭제 가능? | 이유 |
|------|-----------|------|
| K 가 호출하는 10개 .py | ❌ | 지우면 해당 버튼 동작 안 함 |
| PDF책스캔.py | △ | 책범위.xlsx 한 번 만들고 안 갱신할 거면 X. 새 책 추가 시 다시 필요. K 버튼은 제거됐지만 직접 실행 가능 |
| _extract_session.py | △ | 거의 안 쓰지만 Google 세션 만료 디버깅용. 그대로 둠 |
| credentials.json / client_secret.json / authorized_user.json | ❌ | Google API 인증 (Sheets, Drive) |
| 단어관리자료.xlsx | ❌ | 단어관리자료업뎃 + 개별단어장생성 + 내신TEST출력 입력 |
| 모고정답입력/ 하위 | ❌ | 정답 DB · 산출물 캐시 |
| 내신TEST/ / 양식/ / 학생별/ / 단어/ / 어법/ / 요약문완성/ | ❌ | 카테고리별 템플릿 · 출력물 보관 |

## 호출 매핑 (K 버튼 → 스크립트)

### 수업준비 탭

| 버튼 | 스크립트 | 옵션 |
|------|---------|------|
| ① 진행률 체크 | 진행률체크.py | (이번 주 학생 자동 필터) |
| ② 구글업로드+단어관리자료업뎃 | 구글연동.py → 단어관리자료업뎃.py | 체인 (전자 returncode=0 일 때만 후자) |
| ③ 개별단어장 생성 | 개별단어장생성.py | 4개 옵션 (교재명/이름/시작/끝) 다 채우면 단일 행만 |
| ④ 내신TEST 출력 | 내신TEST출력.py | — |

### 모의고사 답지 탭

| 버튼 | 스크립트 | 옵션 |
|------|---------|------|
| ① 모고엑셀답지생성 | 모고엑셀답지생성.py | 학생 필터 |
| ② 학생별오답 | 학생별오답.py | 학생 필터 + 실행단계 체크박스 (1·2·3 기본) |
| ② 학생별오답 [4번만 실행] | 학생별오답.py | `PEDU_STEPS_TO_RUN=4` (PDF 인쇄만) |
| ③ 모고배정추출 | 모고배정추출.py | — |

### 내신 답지 탭

| 버튼 | 스크립트 | 옵션 |
|------|---------|------|
| 내신 답지 생성 | 엑셀답지생성.py | — |
| 내신 답지 업데이트 | 엑셀답지업데이트.py | — |

## 학생별오답 단계 의미

| 단계 | 동작 | 입출력 |
|-----|-----|--------|
| 1 | 오답 수집 | 학생 구글시트 *오답 시트 → 학년별 DB lookup → 학생 .xlsx '원문' 시트 |
| 2 | AI 빈칸 변형 | 학생 .xlsx → Gemini 호출 → '변형문제(Gemini)' 시트 → '변형문제' 시트로 복사 |
| 3 | 한글 출력 | B.부교재 출력 Automation 직접 호출 (헤드리스) → `한글출력/{이름} ... (YYMMDD).hwp` + `.pdf` |
| 4 | PDF 인쇄 | 단계 3 산출 PDF (정답 제외) → `os.startfile(pdf, "print")` → 기본 프린터 |

기본값: `[1, 2, 3]`. 단계 4는 옵션 (체크박스 OFF + 별도 [4번만 실행] 버튼).

## 출력 파일 명명 규칙

### 학생별오답 단계 3·4

`한글출력/` 폴더에 다음 형식으로 저장 (단계 3 끝에 `(YYMMDD)` 접미사 자동 부여):

```
{이름} 모의고사 변형문제 변형문제(통합) (260508).hwp
{이름} 모의고사 변형문제 변형문제(통합) (260508).pdf
{이름} 모의고사 변형문제 변형문제(통합) 정답 (260508).pdf
```

→ 같은 학생 다른 날 출력해도 충돌 안 남.

## 향후 확장 지점

- K 의 `TAB_LAYOUT` 의 items 튜플 3번째 요소가 list 면 체인 실행, str 이면 단일.
- 새 스크립트 추가하려면 `TAB_LAYOUT` 에 한 줄 + 필요시 `_run_*_with_options` 핸들러.
- `_ScriptRunner.run()` 의 `env_override` 파라미터로 자식 프로세스에 옵션 주입.

## 메모리 (Claude 자동 메모리)

K 의 자동전환 시스템은 별도 메모리에 기록됨:
`project_mogo_auto_transition.md` — 학생관리표 AU/AV 수식 + 교재목록 시퀀스 끝 SENTINEL.
