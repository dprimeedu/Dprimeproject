import csv
import io
import time
from datetime import datetime

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.encoding import escape_uri_path
from django.views.decorators.http import require_POST
from django.views.generic import View

from .paste_parser import parse_paste
from .pdf_export import build_html, render_pdf
from .secure_export import encrypt_pedu, DEFAULT_EXPIRY_HOURS
from academy.models import (
    AdditionalText_Data,
    DescriptiveQuestion_Data,
    DetailedExplanation_Data,
    FillinBlank_Data,
    Grammarlv1_Data,
    Grammarlv2_Data,
    Grammarlv3_Data,
    KeyTable,
    ModifiedQuestions_Data,
    OriginalText_Data,
    QuestionData,
    RedBlue_Data,
    SchoolExamTest_Data,
    Summary_Data,
    Translation_Data,
    WordTest_Data,
)


GRADES = ['고1', '고2', '고3']

DATASETS_BASE = [
    {'key': 'mock_exam',   'label': '모의고사',
     'desc_path': 'Z:/home/Drive/교재폴더/모의고사'},
    {'key': 'ebs_high3',   'label': 'EBS 고3',
     'desc_path': 'Z:/home/Drive/교재폴더/EBS/1. 고3 연계교재'},
    {'key': 'ebs_naesin',  'label': 'EBS 내신교재',
     'desc_path': 'Z:/home/Drive/교재폴더/EBS/2. 내신관련 교재'},
    {'key': 'textbook',    'label': '교과서',
     'desc_path': 'Z:/home/Drive/교재폴더/내신'},
]


def _dataset_status():
    """현재 DB의 KeyTable에 행이 있는 카테고리만 enabled=True로 반환."""
    counts = dict(
        KeyTable.objects.values('category')
        .annotate(c=Count('pk_number'))
        .values_list('category', 'c')
    )
    out = []
    for ds in DATASETS_BASE:
        c = counts.get(ds['key'], 0)
        out.append({
            **ds,
            'enabled': c > 0,
            'count': c,
            'desc': f'{ds["desc_path"]} — '
                    + (f'{c}건 sync 완료' if c > 0 else 'sync 대기'),
        })
    return out

UNIT_NUMBERS = (
    [str(i) for i in range(1, 32)]
    + [f'CR{i}' for i in range(1, 7)]
    + [f'T{i}' for i in range(1, 4)]
)

QUESTION_NUMBERS = (
    ['A1', 'A2', 'E1', 'E2', 'G']
    + [str(i) for i in range(1, 36)]
)

OPTIONS = [
    {'key': 'word_test',          'label': '내신단어',     'model': WordTest_Data},
    {'key': 'question_output',    'label': '문제출력',     'model': QuestionData},
    {'key': 'red_blue',           'label': '내신빨파',     'model': RedBlue_Data},
    {'key': 'detailed_expl',      'label': '상세해설',     'model': DetailedExplanation_Data},
    {'key': 'grammar_lv1',        'label': '어법1단계',    'model': Grammarlv1_Data},
    {'key': 'grammar_lv2',        'label': '어법2단계',    'model': Grammarlv2_Data},
    {'key': 'grammar_lv3',        'label': '어법3단계',    'model': Grammarlv3_Data},
    {'key': 'key_point_writing',  'label': '중요영작',     'model': Translation_Data},
    {'key': 'modified_question',  'label': '변형문제',     'model': ModifiedQuestions_Data},
    {'key': 'summary',            'label': '요약문완성',   'model': Summary_Data},
    {'key': 'fill_in_blank',      'label': '객관식빈칸',   'model': FillinBlank_Data},
    {'key': 'additional_text',    'label': '원문추가',     'model': AdditionalText_Data},
    {'key': 'original_text',      'label': '원문모음',     'model': OriginalText_Data},
    {'key': 'school_exam_test',   'label': '내신TEST',     'model': SchoolExamTest_Data},
    {'key': 'file_merge',         'label': '파일병합',     'model': None},
    {'key': 'grammar_lv3_var',    'label': '어법3단계\n(변형문제)', 'model': None, 'disabled': True},
    {'key': 'desc_question',      'label': '직보서술형',   'model': DescriptiveQuestion_Data},
    {'key': 'question_image',     'label': '문제이미지',   'model': None},
    {'key': 'red_blue_only',      'label': '빨파만',       'model': None, 'highlight': 'red'},
]

DEFAULT_CHECKED = {'red_blue', 'detailed_expl', 'modified_question',
                   'original_text', 'school_exam_test', 'desc_question'}

TEST_TYPES = [
    '1학기 중간고사',
    '1학기 기말고사',
    '2학기 중간고사',
    '2학기 기말고사',
    '모의고사',
    '기타',
]


def _number_variants(values):
    """선택한 번호('1', 'A1', ...)에 zero-pad 변형까지 포함한 집합."""
    out = set()
    for v in values:
        v = v.strip()
        if not v:
            continue
        out.add(v)
        if v.isdigit():
            out.add(v.zfill(2))
            out.add(v.lstrip('0') or '0')
    return out


def _matched_pks(grade_selection, category='mock_exam'):
    """선택된 단원/번호로 KeyTable의 PK_number 집합을 반환.

    카테고리별로 단원의 의미가 다름:
      - mock_exam: 단원 → KeyTable.month, 번호 → KeyTable.number
      - 그 외(ebs_*/textbook): 단원 → KeyTable.month (Tkinter 단원 부분),
                                번호 → KeyTable.number
        ('1-A' → month='1', number='A' 형태로 sync됨)
    """
    q = Q()
    has_any = False
    for grade, sel in grade_selection.items():
        units, nums = sel['units'], sel['numbers']
        if not units and not nums:
            continue
        sub = Q(grade=grade) if grade else Q()
        if units:
            sub &= Q(month__in=units)
        if nums:
            sub &= Q(number__in=_number_variants(nums))
        q |= sub
        has_any = True
    base = KeyTable.objects.filter(category=category)
    if not has_any:
        return base.none()
    return base.filter(q)


class IsStaffMixin(UserPassesTestMixin):
    def test_func(self):
        u = self.request.user
        return u.is_authenticated and (
            u.is_staff or u.is_superuser or getattr(u, 'is_academy', False)
        )


def _options_context(selected_keys=None):
    selected_keys = selected_keys or set()
    return [
        dict(o, checked=(o['key'] in selected_keys if selected_keys else o['key'] in DEFAULT_CHECKED))
        for o in OPTIONS
    ]


class PastePreviewView(LoginRequiredMixin, IsStaffMixin, View):
    """스프레드시트 붙여넣기 텍스트 → 학년/단원/번호 JSON으로 파싱."""

    def post(self, request):
        text = request.POST.get('paste_sheet', '')
        result = parse_paste(text)
        return JsonResponse(result)


DOWNLOAD_COLUMNS = ['교재', '학년', '연도', '강(단원)', '번호', '색인', '카테고리']


def _row_dict_to_list(r):
    return [
        r.get('book') or '',
        r.get('grade') or '',
        r.get('year') or '',
        r.get('month') or '',
        r.get('number') or '',
        r.get('total_number') or '',
        r.get('category') or '',
    ]


def _attachment_filename(prefix, ext, name):
    safe = (name or 'export').strip().replace(' ', '_')
    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    return f'{prefix}_{safe}_{stamp}.{ext}'


class DownloadView(LoginRequiredMixin, IsStaffMixin, View):
    """매칭된 KeyTable 행을 CSV/XLSX/.pedu 형식으로 다운로드."""

    def post(self, request):
        fmt = request.POST.get('format', 'csv')
        active_dataset = request.POST.get('dataset', 'mock_exam')
        name = request.POST.get('name', '').strip()
        test_type = request.POST.get('test_type', '').strip()
        selected_options = request.POST.getlist('option')
        grade_selection = {
            g: {
                'units': request.POST.getlist(f'unit_{g}'),
                'numbers': request.POST.getlist(f'qnum_{g}'),
            }
            for g in GRADES
        }

        qs = _matched_pks(grade_selection, category=active_dataset) \
            .order_by('grade', 'year', 'month', 'number')
        rows = list(qs.values('grade', 'year', 'month', 'number',
                              'total_number', 'book', 'category'))

        if fmt == 'xlsx':
            return self._xlsx(rows, name)
        if fmt == 'pedu':
            return self._pedu(request, rows, qs, name, test_type,
                              selected_options, active_dataset, grade_selection)
        if fmt == 'pdf':
            return self._pdf(rows, name, test_type, selected_options,
                             active_dataset, grade_selection)
        return self._csv(rows, name)

    def _csv(self, rows, name):
        buf = io.StringIO()
        # Excel 한글 호환을 위해 BOM 포함
        buf.write('﻿')
        writer = csv.writer(buf)
        writer.writerow(DOWNLOAD_COLUMNS)
        for r in rows:
            writer.writerow(_row_dict_to_list(r))

        resp = HttpResponse(buf.getvalue(), content_type='text/csv; charset=utf-8')
        fname = _attachment_filename('subbook', 'csv', name)
        resp['Content-Disposition'] = f"attachment; filename*=UTF-8''{escape_uri_path(fname)}"
        return resp

    def _pdf(self, rows, name, test_type, selected_options,
             active_dataset, grade_selection):
        """매칭 결과를 단일 PDF 로 다운로드 (WeasyPrint)."""
        # 옵션 키 → 한글 라벨
        labels = [o['label'] for o in OPTIONS if o['key'] in selected_options]

        dataset_label = next(
            (d['label'] for d in DATASETS_BASE if d['key'] == active_dataset),
            active_dataset,
        )

        html = build_html(
            name=name,
            test_type=test_type,
            dataset_label=dataset_label,
            options_labels=labels,
            key_table_rows=rows,
            grade_selection=grade_selection,
        )

        try:
            pdf_bytes = render_pdf(html)
        except (OSError, ImportError) as e:
            # GTK/WeasyPrint 미설치 환경 — 명확한 에러 메시지로 응답
            return HttpResponse(
                f'PDF 생성 환경이 준비되지 않았습니다.\n\n'
                f'서버에 WeasyPrint + GTK 라이브러리 설치가 필요합니다.\n'
                f'(상세: {e})',
                status=503,
                content_type='text/plain; charset=utf-8',
            )

        resp = HttpResponse(pdf_bytes, content_type='application/pdf')
        fname = _attachment_filename('subbook', 'pdf', name)
        resp['Content-Disposition'] = f"attachment; filename*=UTF-8''{escape_uri_path(fname)}"
        return resp

    def _pedu(self, request, rows, qs, name, test_type, selected_options,
              active_dataset, grade_selection):
        """매칭된 detail 데이터까지 모아 .pedu 바이너리로 export."""
        # 옵션 키 → 모델 매핑 (이미 OPTIONS 에 정의됨)
        option_models = {o['key']: o.get('model') for o in OPTIONS if o.get('model')}
        wanted_models = {
            k: option_models[k] for k in selected_options if k in option_models
        }

        pks = list(qs.values_list('pk_number', flat=True))

        # detail payload — 옵션별로 매칭된 행을 모음
        details = {}
        for key, model in wanted_models.items():
            if model is QuestionData:
                # QuestionData는 KEY_TABLE 경유가 아니라 별도 필드 — mock_exam 만 의미 있음
                if active_dataset != 'mock_exam':
                    details[key] = []
                    continue
                q = Q()
                has = False
                for grade, sel in grade_selection.items():
                    if not (sel['units'] or sel['numbers']):
                        continue
                    sub = Q(학년=grade)
                    if sel['units']:
                        sub &= Q(강__in=sel['units'])
                    if sel['numbers']:
                        sub &= Q(번호__in=[int(n) for n in sel['numbers'] if n.isdigit()])
                    q |= sub
                    has = True
                qs_q = model.objects.filter(q) if has else model.objects.none()
                details[key] = list(qs_q.values())
            else:
                details[key] = list(model.objects.filter(pk_number__in=pks).values())

        payload = {
            'schema': 'pedu/sub_book/v1',
            'generated_at': int(time.time()),
            'name': name,
            'test_type': test_type,
            'dataset': active_dataset,
            'grade_selection': grade_selection,
            'options': list(selected_options),
            'key_table': rows,
            'details': details,
        }

        user_id = int(getattr(request.user, 'id', 0) or 0)
        blob = encrypt_pedu(payload, user_id=user_id,
                            expiry_hours=DEFAULT_EXPIRY_HOURS)

        resp = HttpResponse(
            blob,
            content_type='application/octet-stream',
        )
        fname = _attachment_filename('subbook', 'pedu', name)
        resp['Content-Disposition'] = f"attachment; filename*=UTF-8''{escape_uri_path(fname)}"
        resp['X-Pedu-Schema'] = 'sub_book/v1'
        resp['X-Pedu-Expiry-Hours'] = str(DEFAULT_EXPIRY_HOURS)
        return resp

    def _xlsx(self, rows, name):
        try:
            import openpyxl
        except ImportError:
            return HttpResponse('openpyxl 미설치', status=500)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'KEY_TABLE'
        ws.append(DOWNLOAD_COLUMNS)
        for r in rows:
            ws.append(_row_dict_to_list(r))

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        resp = HttpResponse(
            buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        fname = _attachment_filename('subbook', 'xlsx', name)
        resp['Content-Disposition'] = f"attachment; filename*=UTF-8''{escape_uri_path(fname)}"
        return resp


class SubBookView(LoginRequiredMixin, IsStaffMixin, View):
    template_name = 'academy_tools/sub_book.html'

    def _grade_tabs(self, grade_selection=None):
        grade_selection = grade_selection or {}
        return [
            {
                'grade': g,
                'idx': i + 1,
                'unit_numbers': UNIT_NUMBERS,
                'question_numbers': QUESTION_NUMBERS,
                'selected_units': set(grade_selection.get(g, {}).get('units', [])),
                'selected_numbers': set(grade_selection.get(g, {}).get('numbers', [])),
            }
            for i, g in enumerate(GRADES)
        ]

    def get(self, request):
        ctx = {
            'datasets': _dataset_status(),
            'active_dataset': 'mock_exam',
            'grade_tabs': self._grade_tabs(),
            'options': _options_context(),
            'test_types': TEST_TYPES,
        }
        return render(request, self.template_name, ctx)

    def post(self, request):
        selected_options = set(request.POST.getlist('option'))
        active_dataset = request.POST.get('dataset', 'mock_exam')
        grade_selection = {
            g: {
                'units': request.POST.getlist(f'unit_{g}'),
                'numbers': request.POST.getlist(f'qnum_{g}'),
            }
            for g in GRADES
        }
        name = request.POST.get('name', '').strip()
        test_type = request.POST.get('test_type', '').strip()
        extra_preview = request.POST.get('extra_preview', '').strip()

        qs = _matched_pks(grade_selection, category=active_dataset) \
            .order_by('grade', 'year', 'month', 'number')
        matched_pks = list(qs.values_list('pk_number', flat=True))
        total = len(matched_pks)

        # 옵션별 매칭 row 수
        option_results = []
        for o in OPTIONS:
            if o['key'] not in selected_options:
                continue
            model = o.get('model')
            if model is None:
                option_results.append({'label': o['label'], 'count': None, 'note': '미연결'})
                continue
            if model is QuestionData:
                # QuestionData는 KEY_TABLE 경유가 아님 — 학년/연도/강/번호로 직접 매칭
                # (현재는 모의고사 데이터셋에만 적용 — 그 외에는 0 반환)
                if active_dataset != 'mock_exam':
                    cnt = 0
                else:
                    q = Q()
                    has = False
                    for grade, sel in grade_selection.items():
                        if not (sel['units'] or sel['numbers']):
                            continue
                        sub = Q(학년=grade)
                        if sel['units']:
                            sub &= Q(강__in=sel['units'])
                        if sel['numbers']:
                            sub &= Q(번호__in=[int(n) for n in sel['numbers'] if n.isdigit()])
                        q |= sub
                        has = True
                    cnt = model.objects.filter(q).count() if has else 0
            else:
                cnt = model.objects.filter(pk_number__in=matched_pks).count() if matched_pks else 0
            option_results.append({'label': o['label'], 'count': cnt, 'note': ''})

        # 단원별 합계 미리보기 (최대 30행)
        preview_rows = list(
            qs.values('grade', 'year', 'month', 'number', 'total_number', 'book')[:30]
        )

        ctx = {
            'datasets': _dataset_status(),
            'active_dataset': active_dataset,
            'grade_tabs': self._grade_tabs(grade_selection),
            'options': _options_context(selected_options),
            'test_types': TEST_TYPES,
            'pedu_expiry_hours': DEFAULT_EXPIRY_HOURS,
            # 이전 선택값 복원
            'selected_name': name,
            'selected_test_type': test_type,
            'selected_extra_preview': extra_preview,
            # 결과
            'result_total': total,
            'result_options': option_results,
            'result_preview': preview_rows,
            'has_result': True,
        }
        return render(request, self.template_name, ctx)
