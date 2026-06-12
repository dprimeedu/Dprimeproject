# 요약문완성훈련 — 품사변형 기반 생성 → Synology 웹 TEST (2026-06-04)

영어 상세분석의 "서술형 대비 요약문 완성"(빈칸 ⓐ·ⓑ) 방식을, **내신단어 품사변형 단어**가
정답이 되도록 생성해서 **Synology 사이트(dprimeedu.synology.me)** 의 새 "요약문완성훈련" 앱으로
올리는 파이프라인. 기존 Excel→구글 스프레드시트 경로를 대체.

작업은 **두 코드베이스**에 걸친다.
- **생성 측** : `완성(코드)` (Tkinter AI 자동화)
- **웹 측**   : `Dprimeproject` (Django, 운영 NAS)

---

## 1. 실행 방법 (사용자)

`E. AI 자동화` 실행 → "Gemini/Claude 자동화" 창 → **"요약문 생성" 탭**
1. **위 "파일 선택"** : 학교 통합본 xlsx (`원문` + `내신단어` 시트 필수). 파일명에 학교학년 포함(예 `…백현고2…통합.xlsx`).
2. 모델 선택 (gemini-3-flash-preview 등)
3. 옵션 `요약문생성` 체크
4. **"Synology 요약문완성훈련에 업로드"** 체크(기본 켜짐)
5. (아래 "받을 파일"은 **옛 구글시트용 — Synology만 쓰면 비워둠**)
6. **작업 시작**

→ `원문` 지문마다 `내신단어` 품사변형 풀로 요약문 생성 → `요약문완성` 시트 저장 →
   라이브 import API 로 자동 푸시(단원별 replace).

---

## 2. 변경/추가된 파일

### 생성 측 — 완성(코드)  *(로컬 도구, git 미푸시)*
- `CLASS/Gemini.py`
  - `_load_pos_variant_words(wb)` : `내신단어` 시트에서 **해석 끝 영어 품사태그 `(noun)/(adverb)/(adjective)/...`** 붙은 행만 품사변형으로 추출(핵심/동의어/반의어 제외).
  - `_pos_pool_for_unit`, `_school_from_filename`
  - `_create_summary_prompt_from_text(..., pos_pool)` : 빈칸 정답을 품사변형 풀에서 고르도록 프롬프트 주입.
  - `create_summary(..., push_web=True, school=None)` : 단원별 풀 적용 + 생성 후 웹 푸시.
- `CLASS/Claude.py` : 위와 동일(Gemini 헬퍼 재사용). Claude 는 Gemini 상속이라 프롬프트/generate_summary 공유.
- `CLASS/요약문웹동기화.py` *(신규)* : `summary_to_item`(2문장 ⓐ/ⓑ 분리) + `push_summary`(urllib POST).
- `_AI자동화_원본/f-2. Gemini,Claude자동화.py` : "Synology 요약문완성훈련에 업로드" 체크박스 + 핸들러 `push_web` 전달.

### 웹 측 — Dprimeproject  *(origin/main 푸시 + NAS 배포 완료)*
- 신규 `summary/` 앱 : 모델 5개(Unit/Problem/Assignment/Session/BlankAnswer), 뷰/URL/admin/템플릿 7종.
- import API : `POST /training/summary/api/import/` (토큰 `SUMMARY_IMPORT_TOKEN`).
- 학생 TEST : 자동 1차 판정 → 오답 시 **한글뜻 1회** → 재입력 → 제출(채점 대기).
- 관리자 채점 큐 : 빈칸별 O/X → 점수 확정 (`/training/summary/admin/grading/`).
- config : settings(INSTALLED_APPS + `SUMMARY_IMPORT_TOKEN`), urls, base.html, training.html(재원생 메뉴: 영작→**요약문완성**→단어찾기→단어훈련).
- 커밋 `3d697e94` → main 푸시 → NAS 자동배포(`3d697e9`) → **`migrate summary` 수동 적용 완료**(SSH+docker exec).

---

## 3. 배포/운영 메모
- **운영 분기 = `main`** (push 시 ~1분 자동배포: git pull→collectstatic→gunicorn). `migrate`는 **자동 안 됨 → SSH 수동**.
  - `ssh dprime-nas "sudo /usr/local/bin/docker exec django bash -c 'cd /home/Dprimeproject && venv/bin/python manage.py migrate <app>'"`
- 토큰 : 양쪽 기본값 `pedu-summary-2026` 으로 동작 중. 바꾸려면 NAS `.env`의 `SUMMARY_IMPORT_TOKEN` 과 `CLASS/요약문웹동기화.py` 의 `TOKEN` **둘 다** 변경.
- 같은 (학교, 단원) 재업로드 = **덮어쓰기**(중복 안 쌓임).
- 품질 메모 : 빈칸 정답이 풀 단어를 문맥에 맞게 **굴절**(belong→belonging)하는 건 **허용**(사용자 결정).

---

## 4. ⚠️ 꼭 해야 할 TEST (실사용 전 필수)

> 코드/배관은 검증했지만(import 200, 학생흐름 50%, 라이브 푸시 OK), **실제 GUI 1회전 + 학생 응시/채점**은 아직 사람 손으로 확인 안 됨. 아래를 **꼭** 해볼 것.

- [ ] **GUI 1회전**: E. AI 자동화 → 요약문 생성 탭에서 실제 학교 통합본 1개 돌려서, 라이브에 단원/문항 생성되는지(콘솔 "✅ 등록 N문항").
- [ ] **빈칸 정답 품질**: 생성된 ⓐ·ⓑ 정답이 실제로 그 학교 **내신단어 품사변형**인지 육안 확인(엉뚱한 단어 섞이는지).
- [ ] **학생 응시(라이브)**: 재원생 계정으로 `dprimeedu.synology.me/training/summary/` → TEST 시작 → **틀리면 한글뜻 1회 뜨고 재입력 되는지** → 제출 → "채점 대기" 뜨는지.
- [ ] **관리자 채점**: `…/training/summary/admin/grading/` 에서 그 제출 → 빈칸별 O/X → 확정 → 점수 반영되는지.
- [ ] **학생 배정**: 재원생이 메뉴에서 단원을 보려면 `…/admin/units/` 에서 **학생 배정** 필요(미배정이면 학생 홈에 안 뜸).
- [ ] **2문장 분리 점검**: 요약문이 1문장만 나오거나 ⓑ가 비는 케이스 없는지(분리 폴백 확인).

---

## 관련
- 영어분석지 빨파/요약문 소스: [eng_analysis_bbalpa_source.md](eng_analysis_bbalpa_source.md), [eng_analysis_vocab_pipeline.md](eng_analysis_vocab_pipeline.md)
- 내신 답지 업로드 흐름: [naeshin_answer_generation.md](naeshin_answer_generation.md)
- 업로드 규칙: [feedback_upload_cadence] · md 저장 위치: [feedback_md_save_location.md](feedback_md_save_location.md)
