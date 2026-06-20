from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .ip_utils import get_client_ip


@receiver(user_logged_in)
def enforce_single_session(sender, request, user, **kwargs):
    """
    로그인 성공 시:
    1. 기존 세션 삭제 (다른 기기 강제 종료)
    2. 현재 세션 키 저장
    3. 접속 IP 등록/갱신 + 로그 기록
    """
    if not hasattr(user, 'current_session_key'):
        return

    # ── 단일 세션 처리 ──────────────────────────────────────────
    old_key = user.current_session_key
    new_key = request.session.session_key

    if old_key and old_key != new_key:
        from django.contrib.sessions.backends.db import SessionStore
        try:
            SessionStore(session_key=old_key).delete()
        except Exception:
            pass

    user.current_session_key = new_key or ''
    user.save(update_fields=['current_session_key'])

    # ── IP 등록/갱신 ────────────────────────────────────────────
    ip = get_client_ip(request)
    if not ip:
        return

    from .models import UserIP, IPAccessLog

    obj, created = UserIP.objects.get_or_create(
        user=user,
        ip_address=ip,
        defaults={'access_count': 1},
    )
    if not created:
        obj.access_count += 1
        obj.save(update_fields=['access_count', 'last_seen'])

    IPAccessLog.objects.create(
        user=user,
        ip_address=ip,
        status='login_ok',
        path=request.path,
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
    )


@receiver(user_logged_out)
def clear_session_key(sender, request, user, **kwargs):
    """로그아웃 시 세션 키 초기화."""
    if user and hasattr(user, 'current_session_key'):
        user.current_session_key = ''
        user.save(update_fields=['current_session_key'])
