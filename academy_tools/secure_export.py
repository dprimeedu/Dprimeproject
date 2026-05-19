"""
.pedu 보안 export 포맷.

목적:
    매칭된 KEY_TABLE + detail 데이터를 사용자 PC에서 한컴오피스로 변환할 수 있도록
    AES-256-GCM 으로 암호화하고, HMAC-SHA256 으로 변조를 검증할 수 있게 한 파일.

파일 레이아웃 (모든 정수는 big-endian):
    +0   [4]   magic = b"PEDU"
    +4   [1]   version = 1
    +5   [12]  nonce (AES-GCM, 랜덤)
    +17  [4]   user_id (uint32)
    +21  [8]   expiry_unix (uint64, UTC 초)
    +29  [32]  hmac_tag = HMAC-SHA256(hmac_key,  magic..expiry_unix || ciphertext_with_tag)
    +61  [N]   ciphertext_with_tag (AES-256-GCM, 16-byte 인증태그 포함)
                평문 = gzip(json(payload_dict))

검증 순서 (decrypt 시):
    1. magic / version
    2. expiry_unix > now   (시계 슬립 1분 허용)
    3. HMAC 일치
    4. AES-GCM 복호화 (자체 인증태그)
    5. gzip 해제 + JSON 파싱

키 운영:
    - master AES key:  PEDU_AES_KEY  (32 bytes, base64)
    - master HMAC key: PEDU_HMAC_KEY (32 bytes, base64)
    settings 에서 base64 디코드. 부재 시 개발용 결정적 키 생성 (운영 부적합).
"""
from __future__ import annotations

import base64
import gzip
import hmac
import json
import os
import struct
import time
from dataclasses import dataclass
from hashlib import sha256

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MAGIC = b'PEDU'
VERSION = 1
NONCE_LEN = 12
HMAC_LEN = 32
HEADER_LEN = 4 + 1 + NONCE_LEN + 4 + 8 + HMAC_LEN  # 61

DEFAULT_EXPIRY_HOURS = 8
CLOCK_SKEW_SECONDS = 60


class PeduError(Exception):
    """모든 .pedu 관련 오류의 상위 예외."""


class PeduMagicError(PeduError):
    pass


class PeduVersionError(PeduError):
    pass


class PeduExpiredError(PeduError):
    pass


class PeduHmacError(PeduError):
    pass


@dataclass
class PeduHeader:
    version: int
    nonce: bytes
    user_id: int
    expiry_unix: int


def _load_keys():
    """Django settings 에서 마스터 키들을 base64 디코드해서 가져온다."""
    from django.conf import settings
    aes_b64 = getattr(settings, 'PEDU_AES_KEY', None)
    hmac_b64 = getattr(settings, 'PEDU_HMAC_KEY', None)
    if not aes_b64 or not hmac_b64:
        # 개발 환경 폴백 — 운영에서는 settings 에 반드시 지정
        aes_b64 = sha256(b'dev-aes-key-do-not-use-in-prod').digest()
        hmac_b64 = sha256(b'dev-hmac-key-do-not-use-in-prod').digest()
        return aes_b64, hmac_b64
    aes_key = base64.b64decode(aes_b64)
    hmac_key = base64.b64decode(hmac_b64)
    if len(aes_key) != 32 or len(hmac_key) != 32:
        raise PeduError('PEDU_AES_KEY / PEDU_HMAC_KEY 는 base64 인코딩된 32바이트여야 합니다.')
    return aes_key, hmac_key


def encrypt_pedu(
    payload: dict,
    user_id: int,
    expiry_hours: float = DEFAULT_EXPIRY_HOURS,
) -> bytes:
    """payload 를 .pedu 바이너리로 인코드."""
    aes_key, hmac_key = _load_keys()

    plaintext = gzip.compress(json.dumps(
        payload, ensure_ascii=False, separators=(',', ':')
    ).encode('utf-8'))

    nonce = os.urandom(NONCE_LEN)
    aesgcm = AESGCM(aes_key)

    # AAD 에 헤더(논스/유저ID/만료시각/버전)를 묶어 헤더 변조 시 GCM 도 실패하도록
    expiry = int(time.time() + expiry_hours * 3600)
    aad = MAGIC + bytes([VERSION]) + nonce + struct.pack('>I', user_id) + struct.pack('>Q', expiry)
    ciphertext = aesgcm.encrypt(nonce, plaintext, aad)

    hmac_tag = hmac.new(hmac_key, aad + ciphertext, sha256).digest()

    return aad + hmac_tag + ciphertext


def decrypt_pedu(blob: bytes) -> tuple[dict, PeduHeader]:
    """.pedu 바이너리를 검증 + 복호화. 실패 시 PeduError 계열 예외."""
    aes_key, hmac_key = _load_keys()

    if len(blob) < HEADER_LEN + 16:  # 16 = GCM tag
        raise PeduError('파일이 너무 짧습니다.')

    if blob[:4] != MAGIC:
        raise PeduMagicError('PEDU 매직 헤더가 아닙니다.')

    version = blob[4]
    if version != VERSION:
        raise PeduVersionError(f'지원하지 않는 버전: {version}')

    nonce = blob[5:5 + NONCE_LEN]
    user_id = struct.unpack('>I', blob[17:21])[0]
    expiry = struct.unpack('>Q', blob[21:29])[0]
    received_hmac = blob[29:29 + HMAC_LEN]
    ciphertext = blob[HEADER_LEN:]

    aad = blob[:29]

    # 만료 검사
    now = int(time.time())
    if expiry + CLOCK_SKEW_SECONDS < now:
        raise PeduExpiredError(f'파일이 만료되었습니다. (만료 {expiry}, 현재 {now})')

    # HMAC 검증 (constant-time)
    expected_hmac = hmac.new(hmac_key, aad + ciphertext, sha256).digest()
    if not hmac.compare_digest(received_hmac, expected_hmac):
        raise PeduHmacError('HMAC 불일치 — 파일이 변조되었습니다.')

    # AES-GCM 복호화 (내부 인증태그까지 검증)
    aesgcm = AESGCM(aes_key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, aad)
    except Exception as e:
        raise PeduHmacError(f'AES-GCM 복호화 실패: {e}')

    try:
        json_bytes = gzip.decompress(plaintext)
        payload = json.loads(json_bytes.decode('utf-8'))
    except Exception as e:
        raise PeduError(f'payload 파싱 실패: {e}')

    return payload, PeduHeader(
        version=version,
        nonce=nonce,
        user_id=user_id,
        expiry_unix=expiry,
    )


def generate_master_keys() -> tuple[str, str]:
    """운영 키 생성 헬퍼 — 결과를 .env 에 PEDU_AES_KEY / PEDU_HMAC_KEY 로 추가하면 됨."""
    aes = base64.b64encode(os.urandom(32)).decode()
    hmac_k = base64.b64encode(os.urandom(32)).decode()
    return aes, hmac_k
