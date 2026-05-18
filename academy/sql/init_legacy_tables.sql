-- academy 앱의 외부관리 테이블들 (Django models.py에서 managed=False)
-- 원래 본인의 외부 Python 자동화 도구가 만들던 테이블 — NAS 운영 DB 스키마와 동일
-- 로컬 개발 환경에서 sync_exam_data 명령 테스트하려면 이 파일을 한 번 실행해야 함
--
-- 적용 방법:
--   python manage.py dbshell < academy/sql/init_legacy_tables.sql
-- 또는:
--   sqlite3 db.sqlite3 < academy/sql/init_legacy_tables.sql

CREATE TABLE IF NOT EXISTS "question_data" (
  "색인" INTEGER,
  "문제" TEXT,
  "유형" TEXT,
  "지문" TEXT,
  "보기" TEXT,
  "정답" TEXT,
  "변형" TEXT,
  "학년" TEXT,
  "연도" INTEGER,
  "강" INTEGER,
  "번호" INTEGER,
  "단원" TEXT,
  "그림" TEXT
);

CREATE TABLE IF NOT EXISTS "KEY_TABLE" (
  "PK_number" INTEGER,
  "Total_number" TEXT,
  "grade" TEXT,
  "year" INTEGER,
  "month" INTEGER,
  "number" INTEGER,
  "Qtype" TEXT
);

CREATE TABLE IF NOT EXISTS "WordTest" (
  "Index" INTEGER,
  "word" TEXT,
  "english_definition" TEXT,
  "korean_definition" TEXT,
  "PK_number" INTEGER
);

CREATE TABLE IF NOT EXISTS "DetailedExplanation" (
  "Index" INTEGER,
  "Saved_location" TEXT,
  "PK_number" INTEGER
);

CREATE TABLE IF NOT EXISTS "Grammarlv1" (
  "Index" INTEGER,
  "Question" TEXT,
  "PK_number" INTEGER,
  "answer" TEXT
);

CREATE TABLE IF NOT EXISTS "Grammarlv2" (
  "Index" INTEGER,
  "Question" TEXT,
  "Answer" TEXT,
  "PK_number" INTEGER
);

CREATE TABLE IF NOT EXISTS "Grammarlv3" (
  "Index" INTEGER,
  "Question" TEXT,
  "Answer" TEXT,
  "PK_number" INTEGER
);

CREATE TABLE IF NOT EXISTS "Translation" (
  "Index" INTEGER,
  "Sentence" TEXT,
  "Translation" TEXT,
  "ETC" REAL,
  "Key_sentence" TEXT,
  "PK_number" REAL
);

CREATE TABLE IF NOT EXISTS "Summary" (
  "Index" INTEGER,
  "Origin_text" TEXT,
  "Red" TEXT,
  "Blue" TEXT,
  "summary" TEXT,
  "PK_number" INTEGER,
  "Answer" TEXT
);

CREATE TABLE IF NOT EXISTS "Additional_text" (
  "Index" INTEGER,
  "Additional_text" TEXT,
  "PK_number" INTEGER
);

CREATE TABLE IF NOT EXISTS "SchoolExamtest" (
  "Index" INTEGER,
  "Question" TEXT,
  "Type" TEXT,
  "Sentence" TEXT,
  "Option" TEXT,
  "Answer" TEXT,
  "Modified" TEXT,
  "PK_number" INTEGER,
  "Pre_Question" TEXT
);

CREATE TABLE IF NOT EXISTS "Original_text" (
  "Index" INTEGER,
  "Origin_text" TEXT,
  "PK_number" INTEGER
);

CREATE TABLE IF NOT EXISTS "Descriptive_Question" (
  "Index" INTEGER,
  "Que_Location" TEXT,
  "Ans_Location" TEXT,
  "PK_number" INTEGER
);

CREATE TABLE IF NOT EXISTS "RedBlue" (
  "Index" INTEGER,
  "Origin_text" TEXT,
  "Red" TEXT,
  "Blue" TEXT,
  "Ans_location" TEXT,
  "PK_number" INTEGER
);

CREATE TABLE IF NOT EXISTS "FillinBlank" (
  "Index" INTEGER,
  "Question" TEXT,
  "Sentence" TEXT,
  "Options" TEXT,
  "Answer" TEXT,
  "PK_number" INTEGER
);

CREATE TABLE IF NOT EXISTS "Original_Question" (
  "Index" INTEGER,
  "Question" TEXT,
  "Sentence" TEXT,
  "Option" TEXT,
  "Answer" TEXT,
  "Picture" TEXT,
  "PK_number" INTEGER
);

CREATE TABLE IF NOT EXISTS "Modified_Questions" (
  "Index" INTEGER,
  "Question" TEXT,
  "Qtype" TEXT,
  "Sentence" TEXT,
  "Option" TEXT,
  "Answer" TEXT,
  "Modified" TEXT,
  "PK_number" INTEGER
);

CREATE TABLE IF NOT EXISTS "Count_Table" (
  "Table_name" TEXT,
  "PK_number" INTEGER,
  "Count" INTEGER
);
