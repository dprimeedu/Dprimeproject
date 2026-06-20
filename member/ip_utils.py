def get_client_ip(request):
    """
    리버스 프록시(nginx) 뒤에서도 실제 클라이언트 IP를 반환.
    X-Forwarded-For 헤더가 있으면 첫 번째 IP(원본 클라이언트)를 사용.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')
