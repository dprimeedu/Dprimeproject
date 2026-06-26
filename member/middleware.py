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


class AccountTypeSelectionMiddleware:
    """소셜 가입 등으로 학생/학원 유형을 아직 안 고른 계정을 선택 화면으로 유도.

    needs_type_selection=True 인 동안엔 선택 페이지로 리다이렉트(선택/로그아웃/소셜콜백/관리자/정적 제외).
    선택을 마치면 needs_type_selection=False 가 되어 정상 이용.
    """
    SELECT_URL = '/member/select-type/'
    ALLOW_PREFIXES = ('/member/select-type/', '/logout/', '/accounts/', '/admin/', '/static/', '/media/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and getattr(user, 'needs_type_selection', False):
            path = request.path
            if not path.startswith(self.ALLOW_PREFIXES):
                return redirect(self.SELECT_URL)
        return self.get_response(request)
