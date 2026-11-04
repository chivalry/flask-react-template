"""A software passkey that answers both WebAuthn ceremonies as a browser would.

It holds a P-256 key and signs what a real authenticator signs, so the service's calls
into py_webauthn run for real. soft-webauthn does the same job, but its last release is
from 2022 and pins fido2 below 2.0.
"""

import hashlib
import json
import secrets
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, encode_cbor

from src_back.models import User, WebAuthnCredential

# The test app's PUBLIC_BASE_URL, from conftest.py, which imports this module.
ORIGIN = 'https://app.test'

# Authenticator data flags (WebAuthn Level 3, section 6.1).
USER_PRESENT = 0x01
USER_VERIFIED = 0x04
BACKUP_ELIGIBLE = 0x08
BACKED_UP = 0x10
ATTESTED_CREDENTIAL = 0x40

ES256 = -7
TRANSPORTS = ['internal', 'hybrid']


def client_data(ceremony: str, challenge: str, origin: str) -> bytes:
    return json.dumps(
        {'type': ceremony, 'challenge': challenge, 'origin': origin, 'crossOrigin': False}
    ).encode()


class SoftwareAuthenticator:
    """One passkey: a key pair, a credential id, a counter, and its user handle."""

    def __init__(
        self,
        *,
        sign_count: int = 0,
        counter_step: int = 1,
        synced: bool = False,
        aaguid: bytes = bytes(16),
        credential_id: bytes | None = None,
    ) -> None:
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = credential_id or secrets.token_bytes(16)
        self.sign_count = sign_count
        self.counter_step = counter_step
        self.backup_flags = BACKUP_ELIGIBLE | BACKED_UP if synced else 0
        self.aaguid = aaguid
        self.user_handle = b''

    def cose_public_key(self) -> bytes:
        numbers = self.private_key.public_key().public_numbers()
        return encode_cbor(
            {
                1: 2,  # kty: EC2
                3: ES256,  # alg
                -1: 1,  # crv: P-256
                -2: numbers.x.to_bytes(32, 'big'),
                -3: numbers.y.to_bytes(32, 'big'),
            }
        )

    def credential_for(self, user: User) -> WebAuthnCredential:
        # The row registration would save, for a test that starts with a passkey.
        self.user_handle = user.uuid.encode()
        return WebAuthnCredential(
            user=user,
            credential_id=self.credential_id,
            public_key=self.cose_public_key(),
            sign_count=self.sign_count,
            transports=','.join(TRANSPORTS),
        )

    def create(
        self,
        options: dict[str, Any],
        *,
        origin: str = ORIGIN,
        flags: int | None = None,
        transports: list[str] | None = None,
    ) -> dict[str, Any]:
        # What startRegistration resolves with for these options.
        self.user_handle = base64url_to_bytes(options['user']['id'])
        if flags is None:
            flags = USER_PRESENT | USER_VERIFIED | ATTESTED_CREDENTIAL | self.backup_flags
        attested = (
            self.aaguid
            + len(self.credential_id).to_bytes(2, 'big')
            + self.credential_id
            + self.cose_public_key()
        )
        auth_data = self._authenticator_data(options['rp']['id'], flags) + attested
        attestation = encode_cbor({'fmt': 'none', 'attStmt': {}, 'authData': auth_data})
        data = client_data('webauthn.create', options['challenge'], origin)
        return {
            'id': bytes_to_base64url(self.credential_id),
            'rawId': bytes_to_base64url(self.credential_id),
            'type': 'public-key',
            'response': {
                'clientDataJSON': bytes_to_base64url(data),
                'attestationObject': bytes_to_base64url(attestation),
                'transports': TRANSPORTS if transports is None else transports,
            },
            'clientExtensionResults': {},
            'authenticatorAttachment': 'platform',
        }

    def get(
        self, options: dict[str, Any], *, origin: str = ORIGIN, flags: int | None = None
    ) -> dict[str, Any]:
        # What startAuthentication resolves with for these options, one use later.
        self.sign_count += self.counter_step
        if flags is None:
            flags = USER_PRESENT | USER_VERIFIED | self.backup_flags
        auth_data = self._authenticator_data(options['rpId'], flags)
        data = client_data('webauthn.get', options['challenge'], origin)
        signature = self.private_key.sign(
            auth_data + hashlib.sha256(data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            'id': bytes_to_base64url(self.credential_id),
            'rawId': bytes_to_base64url(self.credential_id),
            'type': 'public-key',
            'response': {
                'clientDataJSON': bytes_to_base64url(data),
                'authenticatorData': bytes_to_base64url(auth_data),
                'signature': bytes_to_base64url(signature),
                'userHandle': bytes_to_base64url(self.user_handle),
            },
            'clientExtensionResults': {},
            'authenticatorAttachment': 'platform',
        }

    def _authenticator_data(self, rp_id: str, flags: int) -> bytes:
        rp_id_hash = hashlib.sha256(rp_id.encode()).digest()
        return rp_id_hash + bytes([flags]) + self.sign_count.to_bytes(4, 'big')
