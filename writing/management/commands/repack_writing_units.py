"""이미 '(1/2)','(2/2)' 로 쪼개진 기존 영작 단원들을 하나로 합치고 1..N 재번호.

세트 크기를 15로 바꾸면서, 과거에 20개씩 분할되어 들쭉날쭉해진 단원들을 정리한다.
학생 배정/세션/단원레벨은 합칠 단원으로 이전하고, 문제는 pk 를 보존(시도 기록 유지).

    python manage.py repack_writing_units --dry-run   # 미리보기(변경 없음)
    python manage.py repack_writing_units             # 실제 합치기
    python manage.py repack_writing_units --school 동백고2   # 특정 학교만
"""
from django.core.management.base import BaseCommand

from writing.models import WritingUnit, WritingProblem
from writing.services import packing


class Command(BaseCommand):
    help = "분할된 영작 단원('(n/m)')을 하나로 합치고 문제를 1..N 연속 재번호"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='변경 없이 미리보기')
        parser.add_argument('--school', default='', help='해당 문자열로 시작하는 단원만')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        school = (opts['school'] or '').strip()

        families = packing.find_families()
        if school:
            families = {b: us for b, us in families.items() if b.startswith(school)}

        if not families:
            self.stdout.write(self.style.SUCCESS('합칠 분할 단원이 없습니다.'))
            return

        self.stdout.write(f'대상 단원군 {len(families)}개:'
                          + ('  (DRY-RUN — 변경 없음)' if dry else ''))
        total_merged = 0
        for base, units in sorted(families.items()):
            parts = sorted(units, key=lambda u: (packing.base_title(u.title)[1], u.id))
            counts = {u.title: WritingProblem.objects.filter(unit=u).count() for u in parts}
            total = sum(counts.values())
            sets = (total + packing.SET_SIZE - 1) // packing.SET_SIZE
            detail = ', '.join(f'"{t}"={c}' for t, c in counts.items())
            self.stdout.write(f'\n· {base}')
            self.stdout.write(f'    {detail}')
            self.stdout.write(f'    → 합계 {total}문제 = {packing.SET_SIZE}개 세트 {sets}개'
                              + (f' (마지막 {total - (sets-1)*packing.SET_SIZE}개)' if total else ''))

            if not dry:
                target, merged = packing.consolidate_title(base)
                if target:
                    total_merged += merged
                    self.stdout.write(self.style.SUCCESS(
                        f'    ✓ 단원 {merged}개 흡수 → "{target.title}" '
                        f'({WritingProblem.objects.filter(unit=target).count()}문제)'))

        if dry:
            self.stdout.write(self.style.WARNING(
                '\n미리보기였습니다. 실제로 합치려면 --dry-run 없이 다시 실행하세요.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'\n완료 — 형제 단원 {total_merged}개 합침.'))
