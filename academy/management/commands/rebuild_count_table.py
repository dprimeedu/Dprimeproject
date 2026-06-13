"""
Count_Table 재구축

각 detail 테이블(WordTest, Grammarlv1 등)의 PK_number별 문제 수를
집계해 Count_Table을 갱신

사용:
    python manage.py rebuild_count_table          # 실행
    python manage.py rebuild_count_table --dry-run # 미리보기만

주기적 실행 (cron 예시):
    # 매일 새벽 3시에 자동 실행 
    0 3 * * * /path/to/venv/bin/python /path/to/project/manage.py rebuild_count_table >> /var/log/rebuild_count_table.log 2>&1
"""
import time

from django.core.management.base import BaseCommand
from django.db import connection

TABLE_NAMES = [
    "Additional_text",
    "Descriptive_Question",
    "DetailedExplanation",
    "FillinBlank",
    "Grammarlv1",
    "Grammarlv2",
    "Grammarlv3",
    "Modified_Questions",
    "Original_Question",
    "Original_text",
    "RedBlue",
    "SchoolExamtest",
    "Summary",
    "Translation",
    "WordTest",
]


class Command(BaseCommand):
    help = "Count_Table을 각 detail 테이블의 PK_number별 문제 수로 재구축"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="실제 변경 없이 각 테이블 행 수만 출력",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("🔸 DRY RUN — Count_Table은 변경되지 않습니다\n"))

        started = time.time()

        with connection.cursor() as cursor:
            # 현재 각 테이블 행 수 미리 조회 (dry-run 포함)
            self.stdout.write("테이블별 문제 수 집계:")
            preview = {}
            for table in TABLE_NAMES:
                try:
                    cursor.execute(
                        f'SELECT PK_number, COUNT(*) FROM "{table}" GROUP BY PK_number'
                    )
                    rows = cursor.fetchall()
                    total = sum(cnt for _, cnt in rows)
                    preview[table] = (len(rows), total)
                    self.stdout.write(f"  {table:<25} PK {len(rows):>4}개, 문제 {total:>5}개")
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  {table:<25} 조회 실패: {e}"))
                    preview[table] = (0, 0)

            if dry_run:
                self.stdout.write("")
                self.stdout.write("(dry-run) Count_Table 변경 없이 종료.")
                return

            # 실제 재구축
            self.stdout.write("\nCount_Table 재구축 중...")
            cursor.execute("DELETE FROM Count_Table")

            inserted_total = 0
            for table in TABLE_NAMES:
                try:
                    cursor.execute(
                        f"""
                        INSERT INTO Count_Table (Table_name, PK_number, Count)
                        SELECT %s, PK_number, COUNT(*)
                        FROM "{table}"
                        GROUP BY PK_number
                        """,
                        [table],
                    )
                    inserted_total += cursor.rowcount
                except Exception as e:
                    self.stderr.write(self.style.WARNING(f"  {table} INSERT 실패: {e}"))

        duration = time.time() - started
        self.stdout.write(
            self.style.SUCCESS(
                f"✅ 완료: Count_Table {inserted_total}행 갱신 ({duration:.1f}초)"
            )
        )


def rebuild(stdout=None, stderr=None, dry_run=False):
    """
    다른 management command에서 직접 호출할 때 사용.
    예: from academy.management.commands.rebuild_count_table import rebuild
        rebuild(stdout=self.stdout)
    """
    from django.core.management import call_command
    call_command("rebuild_count_table", dry_run=dry_run,
                 stdout=stdout, stderr=stderr)
