"""교재 단어장 xlsx 폴더 → 배정 가능한 VocabUnit(category='wordbook') 생성.

각 파일 = 한 단어장 단원. 영어/한글 컬럼 자동감지(services.extract_word_pairs).
학생에게 배정하면 100단어 단위 퀴즈렛 세트가 자동 생성된다.

로컬:
    python manage.py import_wordbooks --folder "...\\TEST 자동화\\단어" --recursive --export wb.json
운영(NAS, 폴더 접근 불가):
    python manage.py import_wordbooks --json /tmp/wb.json
"""
import json
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from vocab.models import VocabUnit, VocabWord
from vocab.services import extract_word_pairs


def _clean_title(path):
    name = os.path.splitext(os.path.basename(path))[0].strip()
    if name.startswith('T') and len(name) > 1:   # 파일 접두 'T' 제거
        name = name[1:]
    return name or os.path.basename(path)


class Command(BaseCommand):
    help = "교재 단어장 폴더의 xlsx를 배정 가능한 단원(category='wordbook')으로 적재"

    def add_arguments(self, parser):
        parser.add_argument('--folder', default=None, help='단어장 폴더')
        parser.add_argument('--recursive', action='store_true', help='하위 폴더까지')
        parser.add_argument('--exclude', default='내신단어,파생어휘,내신영작',
                            help='제외할 파일명 포함어(쉼표구분)')
        parser.add_argument('--json', default=None,
                            help='[{title, words:[[영어,한글],...]}] JSON 적재(운영 전송용)')
        parser.add_argument('--export', default=None, help='적재용 JSON 익스포트 경로')
        parser.add_argument('--grade', default='기타')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **o):
        # books: [{title, words:[(w,m)]}]
        books = []
        if o['json']:
            if not os.path.exists(o['json']):
                raise CommandError(f'JSON 없음: {o["json"]}')
            with open(o['json'], encoding='utf-8') as f:
                for b in json.load(f):
                    words = [(w, m) for w, m in b.get('words', [])]
                    if b.get('title') and words:
                        books.append({'title': b['title'], 'words': words})
        else:
            folder = o['folder']
            if not folder or not os.path.isdir(folder):
                raise CommandError(f'폴더 없음: {folder}')
            excludes = [x.strip() for x in (o['exclude'] or '').split(',') if x.strip()]
            files = []
            if o['recursive']:
                for root, _d, fs in os.walk(folder):
                    files += [os.path.join(root, f) for f in fs]
            else:
                files = [os.path.join(folder, f) for f in os.listdir(folder)]
            files = [
                f for f in files
                if f.lower().endswith(('.xlsx', '.xlsm')) and os.path.isfile(f)
                and not any(x in os.path.basename(f) for x in excludes)
            ]
            files.sort()
            self.stdout.write(f'단어장 파일 {len(files)}개 (제외어 {excludes})')
            for fp in files:
                try:
                    pairs = extract_word_pairs(fp)
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'  - {os.path.basename(fp)} 실패: {e}'))
                    continue
                if not pairs:
                    self.stdout.write(self.style.WARNING(f'  - {os.path.basename(fp)} 추출 0 → 스킵'))
                    continue
                books.append({'title': _clean_title(fp), 'words': pairs})
                self.stdout.write(f'  · {_clean_title(fp)[:36]:36s} {len(pairs)}개')

        self.stdout.write(f'단어장 {len(books)}개 준비')

        if o['export']:
            with open(o['export'], 'w', encoding='utf-8') as f:
                json.dump(
                    [{'title': b['title'], 'words': [[w, m] for w, m in b['words']]} for b in books],
                    f, ensure_ascii=False,
                )
            self.stdout.write(self.style.SUCCESS(f'익스포트: {o["export"]} ({len(books)}개 단어장)'))

        if o['dry_run']:
            self.stdout.write('dry-run — 적재 안 함')
            return

        total_words = 0
        for b in books:
            with transaction.atomic():
                unit, _created = VocabUnit.objects.get_or_create(
                    title=b['title'],
                    defaults={'category': VocabUnit.CATEGORY_WORDBOOK, 'grade': o['grade']},
                )
                if unit.category != VocabUnit.CATEGORY_WORDBOOK:
                    unit.category = VocabUnit.CATEGORY_WORDBOOK
                    unit.save(update_fields=['category'])
                VocabWord.objects.filter(unit=unit).delete()
                VocabWord.objects.bulk_create([
                    VocabWord(unit=unit, index=i, word=str(w).strip()[:200], meaning=str(m).strip())
                    for i, (w, m) in enumerate(b['words'], start=1)
                ], batch_size=1000)
            total_words += len(b['words'])

        self.stdout.write(self.style.SUCCESS(
            f"완료 — 단어장 {len(books)}개 / 단어 {total_words}개 "
            f"(교재 단어장 단원 총 {VocabUnit.objects.filter(category=VocabUnit.CATEGORY_WORDBOOK).count()}개)"
        ))
