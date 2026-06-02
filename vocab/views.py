import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from writing.views import is_teacher  # 동일 접근제어 재사용

from .models import VocabUnit, VocabWord, VocabAssignment, StudentWordStar


# ─────────────────────────────────────────────
# 학생 화면
# ─────────────────────────────────────────────

@login_required
def student_home(request):
    """단어훈련 학생 홈 — 배정된 단원 목록 (선생님은 전체)."""
    # 일반 학생인데 학원이 재원생으로 승인 안 했으면 안내
    if not is_teacher(request.user) and not getattr(request.user, 'is_approved', False):
        return render(request, 'vocab/student_pending.html', {})

    if is_teacher(request.user):
        units = list(VocabUnit.objects.filter(is_active=True).order_by('-created_at'))
        is_assigned_view = False
    else:
        assignments = (VocabAssignment.objects
                       .filter(student=request.user)
                       .select_related('unit'))
        units = [a.unit for a in assignments if a.unit.is_active]
        is_assigned_view = True

    unit_ids = [u.id for u in units]

    # 단원별 단어 수 일괄 조회 (N+1 방지)
    word_count_map = {
        row['unit_id']: row['c']
        for row in VocabWord.objects.filter(unit_id__in=unit_ids)
        .values('unit_id').annotate(c=Count('id'))
    }
    # 학생의 단원별 별표 개수 일괄 조회
    star_count_map = {
        row['word__unit_id']: row['c']
        for row in StudentWordStar.objects
        .filter(student=request.user, word__unit_id__in=unit_ids)
        .values('word__unit_id').annotate(c=Count('id'))
    }

    unit_info = []
    for unit in units:
        unit._word_count = word_count_map.get(unit.id, 0)
        unit_info.append({
            'unit': unit,
            'word_count': word_count_map.get(unit.id, 0),
            'star_count': star_count_map.get(unit.id, 0),
        })

    return render(request, 'vocab/home.html', {
        'unit_info': unit_info,
        'is_assigned_view': is_assigned_view,
    })


@login_required
def flashcard_view(request, unit_id):
    """플래시카드 학습 — 단어 ↔ 뜻 뒤집기 + 별표(서버 저장) 집중훈련."""
    unit = get_object_or_404(VocabUnit, pk=unit_id, is_active=True)
    if not is_teacher(request.user):
        if not VocabAssignment.objects.filter(student=request.user, unit=unit).exists():
            messages.error(request, '이 단원은 배정되지 않았습니다.')
            return redirect('vocab:home')

    words = list(unit.words.all().order_by('index'))
    starred_ids = set(
        StudentWordStar.objects
        .filter(student=request.user, word__unit=unit)
        .values_list('word_id', flat=True)
    )
    cards = [{
        'id': w.id,
        'index': w.index,
        'word': w.word,
        'meaning': w.meaning,
        'sub_unit': w.sub_unit,
        'starred': w.id in starred_ids,
    } for w in words]

    return render(request, 'vocab/flashcard.html', {
        'unit': unit,
        'cards_json': json.dumps(cards, ensure_ascii=False),
        'total': len(cards),
        'star_count': len(starred_ids),
    })


@login_required
@require_POST
def star_toggle_api(request):
    """별표 토글 — StudentWordStar 생성/삭제. body: {word_id, starred}."""
    try:
        data = json.loads(request.body or '{}')
        word_id = int(data['word_id'])
        want_starred = bool(data['starred'])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': '잘못된 요청'}, status=400)

    word = get_object_or_404(VocabWord, pk=word_id)

    # 배정 검증 (선생님은 통과)
    if not is_teacher(request.user):
        if not VocabAssignment.objects.filter(student=request.user, unit=word.unit).exists():
            return JsonResponse({'success': False, 'error': '권한 없음'}, status=403)

    if want_starred:
        StudentWordStar.objects.get_or_create(student=request.user, word=word)
    else:
        StudentWordStar.objects.filter(student=request.user, word=word).delete()

    return JsonResponse({'success': True, 'word_id': word_id, 'starred': want_starred})
