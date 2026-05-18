# 프라임에듀 (Dprimeproject)

> 학원용 통합 플랫폼 — 모의고사 데이터 관리·다운로드, 영작훈련, 학생 관리

운영 사이트: [dprimeedu.synology.me](https://dprimeedu.synology.me/)

---

## 🛠 기술 스택

- **백엔드**: Django 5.1.6 (Python 3.10+)
- **DB**: SQLite (WAL 모드, `db.sqlite3`)
- **AI 연동**: Google Gemini (영작훈련 한글뜻 자동 생성)
- **인프라**: Synology NAS + Docker (gunicorn + nginx)
- **프론트엔드**: Bootstrap 5, Font Awesome, vanilla JS

## 🎯 핵심 기능

| 영역 | 설명 |
|---|---|
| **모의고사 다운로드** | 학년/연도/월별 조회·다운로드. 엑셀 → DB 자동 sync 시스템 (`sync_exam_data` 명령) |
| **영작훈련** | 학생용 단어 빈칸 채우기 (3단계 힌트, XP/배지/콤보 게임화) — Gemini AI로 단어별 한글뜻 자동 생성 |
| **학원 관리** | 학원 운영자/학생 회원 분리, 단원 배정, 풀이 기록 |

## 💻 개발 환경 셋업

```powershell
conda activate project       # Python 3.10.20 (miniforge3)
cd "z:\home\Drive\문서 자동화 작업\Workplace\Dprimeproject"
python manage.py migrate     # 최초 1회
python manage.py runserver --insecure
```

브라우저: `http://127.0.0.1:8000/`

> `--insecure` 플래그는 DEBUG=False 상태에서도 정적 파일 서빙하게 함 (로컬 개발용).

## 📁 프로젝트 구조

```
config/              Django 설정 (settings.py, urls.py)
academy/             학원·모의고사 (15개 모델, sync_exam_data 명령)
course/              과정/등록/결제
member/              회원 (커스텀 User 모델: Member)
acad/                학원 관련 (멤버십, 결제)
writing/             영작훈련 앱 (8개 모델, 게임화, AI 통합)
common/              공통 유틸
static/              CSS/JS/이미지
docs/                상세 문서 (아래)
```

## 📚 문서

| 문서 | 내용 |
|---|---|
| [docs/history/2026-05-16_프라임에듀_리뉴얼.md](docs/history/2026-05-16_프라임에듀_리뉴얼.md) | 5/16 작업 정리 (디자인 리뉴얼 + 영작훈련 시스템) |
| [docs/history/2026-05-18_DB통일_sync시스템.md](docs/history/2026-05-18_DB통일_sync시스템.md) | 5/18 작업 정리 (DB 통일 + sync 시스템 + NAS 정리) |
| [docs/history/2026-05-19_재원생시스템_학습실전분리.md](docs/history/2026-05-19_재원생시스템_학습실전분리.md) | 5/19 작업 정리 (재원생 등록·사이드바·학습/실전 분리·리더보드·고유명사) |
| [docs/영작훈련/개발계획.md](docs/영작훈련/개발계획.md) | 영작훈련 앱 개발 계획서 |
| [docs/영작훈련/설계.md](docs/영작훈련/설계.md) | 영작훈련 앱 상세 설계서 (DB/API/UI) |
| [다음_작업.md](다음_작업.md) | 다른 컴 이어 작업 / 토요일 협업자 통보 사항 |

## 🚀 운영 배포

운영 NAS는 `feature/dprime-rewrite` 브랜치를 약 1분 주기로 자동 pull. 로컬에서 `git push` 하면 ~1-2분 후 운영 사이트에 코드 반영됨.

**주의**: 자동 흐름은 **코드만** 옮깁니다. DB 데이터는 별개로 관리 — 새 모의고사 엑셀 갱신 시 `python manage.py sync_exam_data` 수동 실행 필요.

## 👥 팀

- 본 운영: 프라임에듀 (운영자 + 협업자 1명)
- 원본: 권용국, 심민수, 오영록, 이병환 (학원의 민족 → 프라임에듀 리뉴얼 전 원작)
