from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import Member, Profile

class SignupForm(UserCreationForm):
    # 사업자등록증 업로드 필드
    business_registration = forms.FileField(
        required=False,  # 선택적으로 파일을 업로드하도록 설정
        label="사업자등록증 업로드",
        widget=forms.ClearableFileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png"})
    )

    class Meta:
        model = Member
        fields = ['username', 'email', 'password1', 'password2']

# ProfileForm에서 수정할 필드들 정의
class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['bio', 'phone_number']  # bio와 phone_number 필드를 수정 가능하게 설정

class MemberProfileEditForm(forms.ModelForm):
    class Meta:
        model = Member
        fields = ['phone']  # 기본 필드 설정

    phone = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '전화번호'}))

    # __init__ 메서드 오버라이드: is_academy에 따라 business_registration 필드를 동적으로 추가
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.is_academy:  # 만약 사용자가 학원일 경우
            self.fields['business_registration'] = forms.FileField(
                widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
                required=False
            )
        else:
            # 학원이 아닌 경우에는 해당 필드를 삭제
            self.fields.pop('business_registration', None)