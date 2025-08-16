from django.contrib.auth.models import AbstractUser
from django.db import models

class Member(AbstractUser):
    MEMBER_TYPES = (
        ('user', '일반회원'),
        ('academy_admin', '학원운영자'),
        ('admin', '전체관리자'),
    )
    member_type = models.CharField(max_length=20, choices=MEMBER_TYPES, default='user')
    phone = models.CharField(max_length=15, null=True, blank=True)  # 전화번호 필드
    address = models.CharField(max_length=255, null=True, blank=True)  # 주소 필드
    age = models.IntegerField(null=True, blank=True)  # 나이 필드
    phone_verified = models.BooleanField(default=False)
    gps_enabled = models.BooleanField(default=False)
    is_academy = models.BooleanField(default=False)  # 학원 여부
    business_registration = models.FileField(upload_to='business_registrations/', null=True, blank=True)

    username = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'member'
        verbose_name = '회원'
        verbose_name_plural = '회원들'

    def __str__(self):
        return self.email

class Student(models.Model):
    user = models.OneToOneField(Member, on_delete=models.CASCADE)
    enrolled_academy = models.ForeignKey('academy.Academy', on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - Student"

class Profile(models.Model):
    user = models.OneToOneField(Member, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    # 유저 정보에 있음. user에서 끌어오면 됨
    phone_number = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return self.user.username