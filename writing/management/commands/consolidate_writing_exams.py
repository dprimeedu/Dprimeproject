"""내신 시험별 '영작 통합' 마스터로 단원 정리.

각 시험에는 'X ... 영작 통합' 마스터 단원이 있고, 같은 시험의 다른 단원
(외부지문 N, 올림포스 partN, 수능특강 partN, '중요영작' 등)은 마스터에 이미
전부 포함된 중복본이다. (중요영작은 publisher가 '2026 내신 통합' 으로 달라도
내용상 영작 통합의 부분집합이므로 학교+학년으로 묶어 함께 정리한다.)

이 명령은 '학교토큰+학년' 그룹마다:
  1) 제목에 '통합'이 든 마스터를 찾고(여럿이면 문제 수 최다),
  2) 같은 그룹의 다른 활성 단원 중 '문장 집합이 마스터의 부분집합'인 것만 골라
  3) 그 단원의 학생 배정을 마스터로 이전(get_or_create)한 뒤
  4) is_active=False 로 비활성화(숨김)한다. 풀이기록(세션)은 보존.

학교토큰이 없는 단원(레거시 교재 'N과 partN' 등)은 그룹 키가 없어 건드리지 않는다.

TEST 청크는 set_size_for(고15/중20)로 이미 자동 분할되므로, 마스터만 남으면
'고등 15개씩 / 중등 20개씩, 마지막 1개만 자투리'가 된다.

    python manage.py consolidate_writing_exams --dry-run   # 미리보기
    python manage.py consolidate_writing_exams             # 실제 적용
    python manage.py consolidate_writing_exams --school 동백고2   # 일부만
"""
import re
from collections import defaultdict

from django.core.management.base import BaseCommand

from writing.models import (
    WritingUnit, WritingProblem, UnitAssignment, WritingSession,
)
from writing.services import packing


def _norm(s):
    return re.sub(r'[^a-z]', '', (s or '').lower())


# 학교+학년 토큰 (예 '동백고2','동백중2','백현고1') — 제목 우선, 없으면 publisher.
_SCHOOL_RE = re.compile(r'([가-힣A-Za-z]+(?:초|중|고)\s*[1-3])')


def _school_key(unit):
    for s in (unit.title or '', unit.publisher or ''):
        m = _SCHOOL_RE.search(s)
        if m:
            return re.sub(r'\s+', '', m.group(1))
    return None


def _sentence_set(unit):
    out = set()
    for e in WritingProblem.objects.filter(unit=unit).values_list('english', flat=True):
        n = _norm(e)
        if n:
            out.add(n)
    return out


class Command(BaseCommand):
    help = "내신 시험별 '영작 통합' 마스터로 중복 조각 단원을 비활성화하고 배정을 이전"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='변경 없이 미리보기')
        parser.add_argument('--school', default='', help='해당 학교토큰을 포함하는 그룹만 (예: 동백고2)')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        school_filter = (opts['school'] or '').strip()

        groups = defaultdict(list)
        for u in WritingUnit.objects.filter(is_active=True):
            key = _school_key(u)
            if not key:
                continue                       # 학교토큰 없는 레거시 교재 단원은 제외
            groups[(key, u.grade)].append(u)

        total_hidden = 0
        total_moved = 0
        acted_groups = 0

        for key in sorted(groups):
            school, grade = key
            if school_filter and school_filter not in school:
                continue
            us = groups[key]
            masters = [u for u in us if '통합' in u.title]
            if not masters:
                continue
            # 마스터: 제목에 '통합' 포함 중 문제 수 최다
            master = max(masters, key=lambda u: WritingProblem.objects.filter(unit=u).count())
            msent = _sentence_set(master)
            if not msent:
                continue

            size = packing.set_size_for(master.grade)
            mtotal = WritingProblem.objects.filter(unit=master).count()
            sets = (mtotal + size - 1) // size if mtotal else 0

            fragments = []
            for u in us:
                if u.id == master.id:
                    continue
                usent = _sentence_set(u)
                if usent and usent <= msent:          # 마스터의 부분집합인 중복본만
                    fragments.append(u)

            if not fragments:
                continue

            acted_groups += 1
            self.stdout.write(
                f"\n[{school} {grade}, 세트{size}] "
                f"마스터=[{master.id}] '{master.title}' {mtotal}문제 → TEST {sets}청크")

            for u in fragments:
                students = list(UnitAssignment.objects.filter(unit=u)
                                .values_list('student_id', 'assigned_by_id'))
                ns = WritingSession.objects.filter(unit=u).count()
                if not dry:
                    for sid, abid in students:
                        UnitAssignment.objects.get_or_create(
                            student_id=sid, unit=master,
                            defaults={'assigned_by_id': abid})
                    u.is_active = False
                    u.save(update_fields=['is_active', 'updated_at'])
                total_hidden += 1
                total_moved += len(students)
                self.stdout.write(
                    f"   {'(미리보기) ' if dry else '✓ '}숨김 [{u.id}] '{u.title}' "
                    f"({WritingProblem.objects.filter(unit=u).count()}문제) "
                    f"· 배정 {len(students)}명 → 마스터로 이전 · 세션 {ns}개 보존")

        self.stdout.write('')
        if dry:
            self.stdout.write(self.style.WARNING(
                f'미리보기: 그룹 {acted_groups}개 · 숨길 조각 {total_hidden}개 · '
                f'이전될 배정 {total_moved}건. 실제 적용은 --dry-run 없이 실행.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'완료 — 그룹 {acted_groups}개 · 조각 {total_hidden}개 비활성화 · '
                f'배정 {total_moved}건 마스터로 이전.'))
