from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect

from .ip_utils import get_client_ip


class SingleSessionMiddleware:
    """
    한 계정 당 하나의 세션만 허용.
    다른 기기에서 로그인하면 기존 세션이 무효화되고,
    기존 기기의 다음 요청에서 자동 로그아웃 처리.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            stored = getattr(request.user, 'current_session_key', '')
            if stored and stored != request.session.session_key:
                logout(request)
                messages.warning(request, '다른 기기에서 로그인하여 현재 세션이 종료되었습니다.')
                login_url = getattr(settings, 'LOGIN_URL', '/login/')
                return redirect(f'{login_url}?next={request.path}')

            # 세션 시작 첫 번째 요청에만 접속 기록 저장 (중복 방지)
            if not request.session.get('_ip_logged'):
                self._log_session(request)
                request.session['_ip_logged'] = True

        return self.get_response(request)

    def _log_session(self, request):
        ip = get_client_ip(request)
        if not ip:
            return
        try:
            from .models import IPAccessLog
            IPAccessLog.objects.create(
                user=request.user,
                ip_address=ip,
                status='session',
                path=request.path,
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            )
        except Exception:
            pass
