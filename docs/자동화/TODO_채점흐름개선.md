# 2026-05-27 — 내신 채점/검증 흐름 전면 개편

> 학원 PC 세션에서 진행. 청덕고1 마초림 / 초당고3 김민세 / 윤정민·정안나 등 검증 완료.

---

## 1. 학생 답지 양식 새로 (Part1~4 도입)

### 엑셀답지생성.py / 엑셀답지업데이트.py (`Z:\...\TEST 자동화\`)
- **학생 명단 소스 = `0. 학생관리자료.xlsx` 학생Data 시트** (A=이름/B=링크/C=학교) — 옛 `내신정답입력\내신명단.xlsx` 폐기
- **`PEDU_NAESHIN_SCHOOL_FILTER` 환경변수** — 학교 분리 (콤마 다중 가능)
- **변형문제 정답 xlsx → 파일명 `(partN)` 으로 Part1~4 매핑**
- **Part1~4 시트 컬럼 새로**:
  - A=번호 / B=학생입력 / **C=유형** ([순서]/[빈칸]/[어법]) / **D=채점(숨김)** / H=번호(숨김) / I=정답(숨김)
  - 채점 공식 위치: D열, `=IF(B{r}="","",IF(TRIM(B{r})*1=TRIM(I{r})*1,"O","X"))`
  - row2 헤더 자동 갱신: C2='유형' / D2='채점'
- **Part1~4 오답 시트 4개 신설** — 마스터에 양식 없음 → 학생 시트에 `add_worksheet` 직접 생성, 헤더 4열 (번호/정답입력/유형/정답(숨김))
- **단일 `내신오답` 시트 폐기**
- **`apply_naeshin_view()`** — keep 10개 탭만 visible + 순서 정렬 (Part1 → Part1 오답 → Part2 → ... → 내신TEST → 내신객관식빈칸), 외 모든 탭 hidden 일괄 처리
- **생성 흐름의 `_naeshin_guard_` 임시 시트** — del_worksheet 시 visible 0 되는 API 에러 방어

### 마스터 시트 (`1LW5SsH-qscPDPFeXcIfL8wvnbR4SRYAxeE-JU-o-0Qw` = "0. 시험지양식원본")
- 복사 대상 탭 = Part1, Part2, Part3, Part4, 내신TEST, 객관식빈칸 (6개)

---

## 2. 학생 시트 → 로컬 xlsx 동기화

### 학생시트동기화.py (신규, `Z:\...\TEST 자동화\`)
- 학생관리자료 학생Data 의 모든 학생 → 각 학생 구글시트 → `학생별/{이름}.xlsx`
- **모든 탭(visible + hidden) 다운로드** — 구글시트 hidden 속성도 로컬 xlsx 의 `sheet_state='hidden'` 으로 보존
- 매번 덮어쓰기. 파일명 부적합 문자 / openpyxl 31자 제한 자동 처리

### K. TEST 자동화 메뉴 ④ 추가
- 옛: ④ 개별단어장 생성 / ⑤ 내신TEST 출력
- 새: **④ 학생데이터 동기화** / ⑤ 개별단어장 생성 / ⑥ 내신TEST 출력
- 수업준비 사용 안내 흐름도 갱신

---

## 3. Apps Script 채점 코드 패치 + 자동 push 인프라

### Code.js `coreRunExamGrading` (`1_Gs9JcOHvGv3T9D1hLf-15R9JrEwSM6xoA__bPY_-o3THsMW-tqQyFEC` = "학생관리자료통합채점")
- 채점 수식 위치 C → **D**, B(입력) vs I(정답) 숫자 비교
- 오답 시트: 단일 `내신오답` → **`{sheetName} 오답`** (Part1 오답 ~ Part4 오답), 4열 (번호/정답입력(빈)/유형/정답(숨김))
- **풀이된 행 hideRows** — 다음 풀이 시 새 문제가 시트 상단에 보이도록 (모고 채점 흐름과 동일 패턴)
- 회차별 색 누적 그대로 유지

### clasp 환경 셋업 (학원 PC 한 번만)
- Node.js LTS (winget) + `@google/clasp` 3.3.0 글로벌 설치
- `clasp login` → `dprimeedu@gmail.com` 토큰 ~/.clasprc.json 저장
- `.clasp.json` 의 scriptId = `1_Gs9JcOH…` (진짜 프로젝트, 마스터 시트 채점 메뉴와 연결됨)

### 자동 push 규칙
- `AppsScript_답지생성/Code.js` 또는 `appsscript.json` 수정 시 즉시 PowerShell 로 `clasp push --force` 실행
- 메모리에 행동 패턴 박제: [feedback_clasp_push.md](C:\Users\primeedu\.claude\projects\z--home-Drive-----------------\memory\feedback_clasp_push.md)

### 옛 잘못된 scriptId 주의
- `1JfvTSf…` — 사용자 Drive 에서 접근 불가능한 미스 ID (옛 계정 잔재). **다시 쓰지 말 것**

---

## 4. 학생 과제 매칭 사전 검증 + 강제 숨김

### 학생과제매칭검증.py (신규, `Z:\...\TEST 자동화\`)

**1단계 — 강제 숨김 (출석 학생만):**
- 학생관리표(`16lTRSL…` "0. 학생관리자료" 시트 "학생관리표") 의 모든 박제 행 중 **오늘 등원 외 학생/날짜 = 과거** → 학생별 AP/AR 누적
- 학생 시트의 각 탭에서 hidden 안 된 행(>= DATA_START_ROW=8) 검사 → 두 룰 OR 매칭 시 hideRows
  - (a) `name_match`: B열 값(YYYY-MM-DD) 또는 시트명이 박제 task 와 매칭
  - (b) **시간 기반**: 박제된 가장 최근 모고 (year,month) ≤ threshold 인 모든 행 (안 푼 옛 회차도 일괄 정리)

**2단계 — 검증 (강제 숨김 이후 상태 기준):**
- 오늘 등원 학생의 AP/AR 가 학생 시트의 어느 탭(visible 첫 문제) 와 매칭되는지
- `name_match` 패턴: 시트명/모고번호/YYYY-MM-DD → 연·월

### 오늘 등원 학생 식별 — E열(박제 날짜) 기준
- `_today_str()` = `f"{m.month}/{m.day} {weekday_kr[weekday()]}"` 예) `'5/27 수'`
- E열 == today_str 인 학생만 검증/숨김 대상
- **마초림(E=5/26 화) 같이 박제는 됐지만 오늘 미등원인 학생 자동 제외**
- 옛 가정 "HEADER_ROW=19" 폐기 — E열 기반이라 헤더 위치 무관

### K. TEST 자동화 메뉴 ③ chain 갱신
- 옛: ③ 단어관리+구글업로드 (단어관리자료업뎃 → 구글연동)
- 새: **③ 단어관리+구글업로드+과제검증** (단어관리자료업뎃 → 구글연동 → **학생과제매칭검증**)

---

## 5. 검증 패턴 (2026-05-27 기준)

| 케이스 | 학생 | 결과 |
|---|---|---|
| 청덕고1 답지 생성 | 마초림 | Part1 470 / 내신TEST 97 / Part1~4 오답 4개 add |
| 초당고3 답지 생성 | 김민세 | Part1 388 / 내신TEST 33 / 내신객관식빈칸 34 / Part1~4 오답 4개 add |
| 청덕고1 답지 업데이트 | 마초림 | 7시트 유지 + 데이터 갱신 |
| 초당고3 답지 업데이트 | 김민세 | 동일 |
| 학생 시트 동기화 | 마초림 | 24개 탭 (visible 10, hidden 14) |
| 학생 시트 동기화 | 김민세 | 21개 탭 (visible 10, hidden 11) |
| 채점 시뮬레이션 | 마초림 Part1 | D열 O/X 자동, 4/20 = 20점 |
| 채점 시뮬레이션 | 김민세 Part1 | 6/20 = 30점, 행 hidden 적용 OK |
| 오늘 등원 12명 검증 | 정상 9 / 미매칭 3 | 마초림/권효재(E=어제) 자동 제외 |

---

## 6. 남은 미매칭 (사용자 결정 대기)

```
- 이다영  AP 미매칭 → '2022년 고2 06월 모의고사'    ← 사용자가 학생관리표 정정 예정
- 허지윤  AR 미매칭 → '내신 학교 진도 나간데까지 빨파'  ← 내신 로직 (다음에 룰 알려줄 예정)
- 송지우  AP 미매칭 → '백현고2 기말고사 내신 빨파'    ← 내신 로직 (동일)
```

내신 빨파 매칭 룰은 사용자가 다음 세션에 사양 알려주면 추가.

---

## 7. 메모리 갱신 항목

- [naeshin_answer_generation.md](C:\Users\primeedu\.claude\projects\z--home-Drive-----------------\memory\naeshin_answer_generation.md) — Part1~4 양식, 학생Data 소스, 학교 필터, 마스터 시트 탭 구조
- [feedback_clasp_push.md](C:\Users\primeedu\.claude\projects\z--home-Drive-----------------\memory\feedback_clasp_push.md) — Code.js 수정 후 자동 clasp push 패턴 (진짜 scriptId 박힘)
- [student_management_xlsx.md](C:\Users\primeedu\.claude\projects\z--home-Drive-----------------\memory\student_management_xlsx.md) — 학생관리표 헤더 위치 가정 폐기 + E열 기반 등원 식별 명시

---

## 8. 다음 단계 후보

1. **내신 빨파 매칭 룰** — 사용자가 사양 알려주면 추가
2. **이다영 학생관리표 정정** — 사용자 손
3. **K. TEST 자동화 ⑤ 개별단어장 생성 후 동기화 자동 연결 여부 검토** — 사용자가 시점 결정 보류 중 (sync_student_local_xlsx 함수는 엑셀답지생성/업데이트 안에 정의됐으나 호출은 주석 처리)
4. **Apps Script 채점 메뉴 시각 검증** — 마초림/김민세 마스터 시트에서 메뉴 5번 클릭 후 실제 동작 확인 (시뮬레이션은 통과)
5. **변형문제 재생성 (오답 분석 기반)** — `학생별내신오답.py` 신규 또는 `f-2. Gemini,Claude자동화.py` 확장
