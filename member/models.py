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
        ('full', '모고 전체'),
    )
    academy_access = models.CharField(
        max_length=15, choices=ACADEMY_ACCESS, default='none',
        verbose_name='모고 데이터 접근범위',
        help_text="외부/학원 계정용. none=접근X, variant_view=변형문제 열람만, "
                  "variant_down=변형문제 열람+다운로드, full=모고 전체. "
                  "관리자(is_staff·is_superuser)는 이 값과 무관하게 항상 전체.",
    )
    phone = models.CharField(max_length=15, null=True, blank=True)
    is_academy = models.BooleanField(default=False)
    business_registration = models.FileField(upload_to='business_registrations/', null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now)

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
        """모고 데이터 전체(모든 카테고리) 열람·다운로드 가능 여부."""
        return self.is_admin_level or self.academy_access == 'full'

    @property
    def can_view_variant(self) -> bool:
        """변형문제(최소) 이상 '열람' 가능 여부. variant_view부터 허용, full 포함."""
        return self.can_view_mock_full or self.academy_access in ('variant_view', 'variant_down')

    @property
    def can_download(self) -> bool:
        """볼 수 있는 자료를 '다운로드'할 권한. variant_down(승인) 또는 full/관리자."""
        return self.can_view_mock_full or self.academy_access == 'variant_down'


class Profile(models.Model):
    user = models.OneToOneField(Member, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    # 유저 정보에 있음. user에서 끌어오면 됨
    phone_number = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return self.user.username