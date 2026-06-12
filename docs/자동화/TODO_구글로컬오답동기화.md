# 구글 → 로컬 오답 시트 동기화 (개별성적표용 TODO)

## 배경 (2026-05-14 결정)

- G드라이브 `\내 드라이브\개인별 단어장\학생별\*.xlsx` 사본 생성 코드 제거 — 학생이 실수로 xlsx를 누르는 문제 때문. 기존 38개 파일도 삭제.
- 로컬 `TEST 자동화\학생별\*.xlsx` 는 Synology Drive 로 자동 동기화 → 백업은 이걸로 충분.
- **문제**: 학생 풀이/오답 누적은 구글 시트 안의 `"~오답"` 시트들에만 쌓이고, 로컬 xlsx에는 출제 스냅샷만 있음. 개별성적표 작성 시 누적 오답 데이터를 활용하려면 구글에서 로컬로 끌어와야 함.

## 요구사항

| 항목 | 결정 |
|---|---|
| 방향 | **구글 → 로컬 단방향** (로컬에서 구글로 올리지 않음) |
| 대상 시트 | 시트 이름에 `"오답"`이 포함된 **모든** 시트 (어법오답, 단어오답, 내신오답 등) |
| 실행 시점 | **개별성적표 스크립트가 데이터 수집 직전 호출**. 출제 스크립트(`개별단어장생성.py`)에서는 동기화하지 않음 |
| 대상 학생 | 개별성적표를 생성하는 그 학생들만 (전체 학생 매번 동기화는 비용↑) |

## 동작

1. 학생 이름으로 `TARGET_FOLDER_ID` 안에서 구글 스프레드시트 검색
2. `[ws for ws in student_gs.worksheets() if "오답" in ws.title]` 로 대상 시트 추림
3. 로컬 `학생별/{학생}.xlsx` 열기 (없으면 신규 워크북)
4. 각 구글 시트 → 동일 이름으로 로컬에 쓰기 (같은 이름 시트가 이미 있으면 **삭제 후 재생성**)
5. 저장

> 로컬 xlsx에 이미 들어있는 `"단어"` / `"어법"` 등 **출제 시트는 절대 건드리지 않음** — `"오답"` 포함 시트만 갈아끼움.

## 구현 힌트

- 어법오답 읽기 패턴 재사용: [`개별단어장생성.py:558-590`](개별단어장생성.py)
  ```python
  q_file = f"name = '{student_name}' and '{TARGET_FOLDER_ID}' in parents and trashed = false"
  res = drive_service.files().list(q=q_file, fields="files(id)").execute()
  student_gs = gc.open_by_key(res['files'][0]['id'])

  target_ws = [w for w in student_gs.worksheets() if "오답" in w.title]
  ```
- 시트 데이터 가져오기: `ws.get_all_values()` → 2D list (빈 셀 포함한 사각 영역). 빈 시트는 `[]` 또는 `[[]]` 가능 → 길이 체크 필요.
- 로컬 쓰기: openpyxl `load_workbook(local_xlsx_path)`, `del wb[name]` → `create_sheet(name)` → `ws.append(row)` 반복.
- 인증: `개별단어장생성.py` 상단의 `client_secret.json` / `authorized_user.json` 흐름 그대로 재사용 가능.

## 주의 / 엣지케이스

- **API 호출 비용**: 학생 N명 × 시트 M개 = N·M 콜. 학생 사이에 `time.sleep(0.5~1)` 정도 둘 것.
- **학생 시트가 없는 경우** (구글에서 찾기 실패) — 그 학생만 스킵하고 진행, 에러로 중단하지 말 것.
- **로컬 xlsx 가 열려 있을 때** 저장 실패 → `PermissionError` 캐치해서 다음 학생으로.
- **셀 서식 무시**: `get_all_values()` 는 텍스트만 가져옴. 채점 수식, 빨강 배경 등은 옮기지 않음. 개별성적표는 데이터(텍스트)만 필요하므로 OK.
- **헤더 행**: 어법오답 시트는 첫 1~2행이 헤더. 로컬도 같은 구조로 그대로 옮기면 됨.

## 의존성

- `개별단어장생성.py` 의 다음 객체가 인증된 상태로 필요:
  - `gc` (gspread Client)
  - `drive_service` (Google Drive API v3 client)
  - `TARGET_FOLDER_ID` (학생 스프레드시트들이 모인 폴더 ID)
- 헬퍼로 분리해 `from 개별단어장생성 import ...` 보다는, 인증 부분만 공용 모듈로 빼고 양쪽에서 import 하는 게 깔끔.

## 미해결 — 작업 시 결정할 것

- 로컬 xlsx 파일명 규칙이 `{학생}.xlsx` 그대로면 OK. 학기/날짜별로 분리할지는 개별성적표 설계 시 결정.
- 동기화 시점의 누적 데이터를 "지금까지 누적"으로 둘지, "최근 N회분"으로 자를지 — 개별성적표 표시 정책에 따라.
