from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
from django.utils import timezone

class MemberManager(BaseUserManager):
    def create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email은 필수입니다.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        return self.create_user(email, password, **extra_fields)
    
class Member(AbstractBaseUser, PermissionsMixin):
    MEMBER_TYPES = (
        ('user', '학생'),
        ('academy_admin', '학원운영자'),
        ('admin', '전체관리자'),
    )
    objects = MemberManager()
    email = models.EmailField(unique=True, null=True, blank=True)
    login_id = models.CharField(
        max_length=50, unique=True, null=True, blank=True,
        verbose_name='로그인 ID',
        help_text='학원이 등록한 재원생용 ID (영문/숫자). 일반 회원가입자는 이메일로 로그인.',
    )
    username = models.CharField(max_length=150, verbose_name='이름')
    nickname = models.CharField(
        max_length=30, blank=True, default='',
        verbose_name='별명',
        help_text='리더보드/대전에서 표시될 별명. 비어있으면 로그인 ID로 표시.',
    )
    school = models.CharField(
        max_length=30, blank=True, default='',
        verbose_name='학교',
        help_text="학년 숫자를 뺀 학교명. 예: '동백중', '백현고'. 단원 자동배정 매칭에 사용.",
    )
    grade = models.CharField(
        max_length=10, blank=True, default='',
        verbose_name='학년',
        help_text="단원 학년과 동일 포맷. 예: '중2', '고3'. 단원 자동배정 매칭에 사용.",
    )
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_approved = models.BooleanField(
        default=False, verbose_name='재원생 승인',
        help_text='학원이 재원생으로 인정한 경우 True. 재원생 메뉴 접근에 필요.',
    )
    member_type = models.CharField(max_length=20, choices=MEMBER_TYPES, default='user')
    ACADEMY_ACCESS = (
        ('none', '접근 없음'),
        ('variant_view', '변형문제 열람만'),
        ('variant_down', '변형문제 열람+다운로드'),
        ('view_down_2026', '2026년 열람+다운로드'),
        ('full', '모고 전체'),
    )
    # 연도 제한이 있는 권한 → 해당 연도 문자열 매핑. 신규 연도(예: 2027) 추가 시 여기에 1줄.
    YEAR_LIMITED_ACCESS = {
        'view_down_2026': '2026',
    }
    academy_access = models.CharField(
        max_length=15, choices=ACADEMY_ACCESS, default='none',
        verbose_name='모고 데이터 접근범위',
        help_text="외부/학원 계정용. none=접근X, variant_view=변형문제 열람만, "
                  "variant_down=변형문제 열람+다운로드, view_down_2026=2026년 자료만 열람+다운로드, "
                  "full=모고 전체. "
                  "관리자(is_staff·is_superuser)는 이 값과 무관하게 항상 전체.",
    )
    phone = models.CharField(max_length=15, null=True, blank=True)
    is_academy = models.BooleanField(default=False)
    business_registration = models.FileField(upload_to='business_registrations/', null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now)
    current_session_key = models.CharField(
        max_length=40, blank=True, default='',
        verbose_name='현재 세션 키',
        help_text='단일 세션 제한 — 새 로그인 시 갱신, 로그아웃 시 초기화.',
    )
    max_allowed_ips = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='최대 허용 IP 수',
        help_text='0 = 무제한. 1 이상 설정 시 해당 수만큼의 IP에서만 로그인 가능.',
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'member'
        verbose_name = '회원'
        verbose_name_plural = '회원들'

    def __str__(self):
        return self.login_id or self.email or f'user#{self.pk}'

    @property
    def display_name(self) -> str:
        """리더보드/대전 표시용 — 별명 > login_id > username 순."""
        return (self.nickname or '').strip() or (self.login_id or '').strip() or (self.username or '').strip() or f'user#{self.pk}'

    @property
    def is_admin_level(self) -> bool:
        """관리자급 — 모고 전체 접근 + 운영 메뉴. is_staff/is_superuser만.
        학원(is_academy) 셀프가입 계정은 관리자가 아니며 academy_access로 제어(기본 variant=변형문제만)."""
        return bool(self.is_staff or self.is_superuser)

    @property
    def can_view_mock_full(self) -> bool:
        """모고 데이터 전체(모든 카테고리) 열람·다운로드 가능 여부.
        view_down_2026 은 카테고리는 전체 권한이지만 연도가 2026 으로 제한된다(뷰 단에서 필터)."""
        return self.is_admin_level or self.academy_access in ('full', 'view_down_2026')

    @property
    def can_view_variant(self) -> bool:
        """변형문제(최소) 이상 '열람' 가능 여부. variant_view부터 허용, full 포함."""
        return self.can_view_mock_full or self.academy_access in ('variant_view', 'variant_down')

    @property
    def can_download(self) -> bool:
        """볼 수 있는 자료를 '다운로드'할 권한. variant_down·view_down_2026·full·관리자."""
        return self.is_admin_level or self.academy_access in ('variant_down', 'view_down_2026', 'full')

    @property
    def access_year_limit(self) -> str | None:
        """연도 제한이 있으면 그 연도 문자열, 없으면 None.
        예: view_down_2026 → '2026'. 관리자/full 은 항상 제한 없음.
        연도별 추가는 YEAR_LIMITED_ACCESS 에 1줄 추가만 하면 된다."""
        if self.is_admin_level:
            return None
        return self.YEAR_LIMITED_ACCESS.get(self.academy_access)


class UserIP(models.Model):
    """계정별 등록된 IP 목록 (로그인 허용 IP 관리)."""
    user = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name='allowed_ips',
        verbose_name='회원',
    )
    ip_address = models.GenericIPAddressField(verbose_name='IP 주소')
    first_seen = models.DateTimeField(auto_now_add=True, verbose_name='최초 접속')
    last_seen = models.DateTimeField(auto_now=True, verbose_name='최근 접속')
    access_count = models.PositiveIntegerField(default=1, verbose_name='접속 횟수')

    class Meta:
        db_table = 'member_user_ip'
        unique_together = [('user', 'ip_address')]
        verbose_name = '허용 IP'
        verbose_name_plural = '허용 IP 목록'
        ordering = ['-last_seen']

    def __str__(self):
        return f'{self.user} — {self.ip_address}'


class IPAccessLog(models.Model):
    """IP 접속 기록 (로그인·세션·차단 이력)."""
    STATUS_CHOICES = [
        ('login_ok',   '로그인 성공'),
        ('login_fail', '로그인 실패'),
        ('ip_blocked', 'IP 차단'),
        ('session',    '세션 접속'),
    ]
    user = models.ForeignKey(
        Member, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ip_logs', verbose_name='회원',
    )
    ip_address = models.GenericIPAddressField(verbose_name='IP 주소')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='session', verbose_name='상태')
    path = models.CharField(max_length=500, blank=True, verbose_name='경로')
    user_agent = models.CharField(max_length=500, blank=True, verbose_name='브라우저')
    accessed_at = models.DateTimeField(auto_now_add=True, verbose_name='접속 시각')

    class Meta:
        db_table = 'member_ip_access_log'
        verbose_name = 'IP 접속 기록'
        verbose_name_plural = 'IP 접속 기록'
        ordering = ['-accessed_at']

    def __str__(self):
        user_str = str(self.user) if self.user else '비로그인'
        return f'[{self.get_status_display()}] {user_str} — {self.ip_address}'


class Profile(models.Model):
    user = models.OneToOneField(Member, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    # 유저 정보에 있음. user에서 끌어오면 됨
    phone_number = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return self.user.username