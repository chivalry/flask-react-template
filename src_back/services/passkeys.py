"""Passkeys: the WebAuthn ceremonies that add one and sign in with one, and their upkeep.

The relying party is the site at ``PUBLIC_BASE_URL``, so passkeys are off without it.
Each ceremony's challenge travels in a signed token, which the routes keep in the
ceremony's own cookie (:mod:`src_back.services.passkey_state`) and spend, so this module
keeps no challenge. ``ai/auth.md`` explains the flow and what the cookie does not defend
against.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from flask import current_app
from sqlalchemy.exc import IntegrityError
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import (
    decode_credential_public_key,
    decoded_public_key_to_cryptography,
    parse_authentication_credential_json,
    parse_registration_credential_json,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticationCredential,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    CredentialDeviceType,
    PublicKeyCredentialDescriptor,
    RegistrationCredential,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)
from webauthn.registration.verify_registration_response import VerifiedRegistration

from src_back.extensions import db
from src_back.models import User, WebAuthnCredential
from src_back.services.audit_log import AuditTrail
from src_back.services.auth import lock_sign_in_methods, require_another_sign_in_method
from src_back.services.errors import DuplicateRecordError, PasskeyError
from src_back.services.passkey_state import (
    CHALLENGE_TTL_SECONDS,
    challenge_from_token,
    new_challenge_token,
)

_log = logging.getLogger(__name__)

EXPIRED = 'That passkey request expired. Try again.'
NOT_VERIFIED = 'The passkey could not be verified.'
ALREADY_REGISTERED = 'That passkey is already registered.'

MAX_CREDENTIAL_ID_BYTES = 1023
"""The longest credential id WebAuthn allows (Level 3, section 7.1).

py_webauthn does not check it, and PostgreSQL's unique index refuses an entry over about
2.7 KB that does not compress, with an error that the duplicate check does not catch.
"""

_DEFAULT_PORTS = {'http': 80, 'https': 443}

_KNOWN_TRANSPORTS = frozenset(transport.value for transport in AuthenticatorTransport)

_SIGN_IN_REJECTED = (WebAuthnException, ValueError)
"""What a malformed or forged sign-in answer raises.

py_webauthn wraps most failures in a ``WebAuthnException``, but a user handle that is not
base64url raises ``binascii.Error``, and a saved key cryptography refuses a
``ValueError``. A registration answer can raise far more, so
:func:`verify_registration` refuses any exception.
"""

# Each add, rename, and delete changes how an account can sign in. Only admins may read
# these histories: the history route serves any signed-in account a table that is not
# admin-only, which would show every account's passkey nicknames. A sign-in changes only
# the counter, the backup state, and last_used_at, which the trail does not record.
PASSKEY_AUDIT_TRAIL = AuditTrail(
    WebAuthnCredential,
    ('user_id', 'nickname', 'aaguid'),
    label_field='nickname',
    admin_only=True,
)


@dataclass(frozen=True)
class RelyingParty:
    """The site passkeys belong to, as browsers see it.

    ``id`` is the host name a passkey is bound to, ``name`` what the browser's prompt
    calls the site, and ``origin`` the scheme, host, and port that pages report.
    """

    id: str
    name: str
    origin: str


def rp_settings() -> RelyingParty | None:
    """Derive the relying party from ``PUBLIC_BASE_URL``.

    The RP ID is the host name alone. The origin is rebuilt as a browser reports it, with
    the host lowercased and a default port dropped, because py_webauthn compares origins
    as exact strings.

    Returns:
        The relying party, or ``None`` when ``PUBLIC_BASE_URL`` is unset, names no host,
        or is not a valid URL, such as one whose port is not a number, which turns the
        ceremonies off.
    """
    try:
        parts = urlsplit(current_app.config['PUBLIC_BASE_URL'] or '')
        hostname, port = parts.hostname, parts.port
    except ValueError:
        _log.warning('PUBLIC_BASE_URL is not a valid URL, so passkeys are off.')
        return None
    if not hostname:
        return None
    origin = f'{parts.scheme}://{hostname}'
    if port is not None and port != _DEFAULT_PORTS.get(parts.scheme):
        origin = f'{origin}:{port}'
    name = current_app.config['WEBAUTHN_RP_NAME']
    return RelyingParty(id=hostname, name=name, origin=origin)


def _descriptor(passkey: WebAuthnCredential) -> PublicKeyCredentialDescriptor:
    """Describe a saved passkey for the exclude list.

    Args:
        passkey: The saved passkey.

    Returns:
        Its credential id, with the transports the browser reported when it was added,
        less any a later py_webauthn no longer knows.
    """
    names = (passkey.transports or '').split(',')
    known = [name for name in names if name in _KNOWN_TRANSPORTS]
    transports = [AuthenticatorTransport(name) for name in known]
    return PublicKeyCredentialDescriptor(
        id=passkey.credential_id, transports=transports or None
    )


def registration_options(user: User, rp: RelyingParty) -> tuple[str, str]:
    """Build the options for adding a passkey, and sign their challenge.

    The passkey must be discoverable, so it can sign in without an email, and must verify
    its user, with a biometric, a screen lock, or a PIN. The account's ``uuid`` is its
    user handle, which says nothing about the person. Each passkey the account has is
    excluded, so a device that holds one says so instead of making a second.

    Args:
        user: The signed-in account adding a passkey.
        rp: The relying party.

    Returns:
        The options as JSON, for ``startRegistration``, and the token that carries their
        challenge, issued to this account, for the registration cookie.
    """
    options = generate_registration_options(
        rp_id=rp.id,
        rp_name=rp.name,
        user_id=user.uuid.encode(),
        user_name=user.email,
        user_display_name=user.email,
        timeout=CHALLENGE_TTL_SECONDS * 1000,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[_descriptor(passkey) for passkey in user.passkeys],
    )
    token = new_challenge_token('register', options.challenge, user_id=user.id)
    return options_to_json(options), token


def _new_passkey(
    verified: VerifiedRegistration,
    credential: RegistrationCredential,
    nickname: str | None,
) -> WebAuthnCredential:
    """Build the row for a verified registration.

    py_webauthn has dropped the transports it does not know; a repeated one is kept once,
    so the column cannot overflow.

    Args:
        verified: What py_webauthn verified.
        credential: The parsed answer, which holds the transports.
        nickname: The passkey's name, or ``None``.

    Returns:
        The unsaved passkey.
    """
    transports = credential.response.transports or []
    names = dict.fromkeys(transport.value for transport in transports)
    return WebAuthnCredential(
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=','.join(names) or None,
        aaguid=verified.aaguid,
        backup_eligible=(
            verified.credential_device_type == CredentialDeviceType.MULTI_DEVICE
        ),
        backup_state=verified.credential_backed_up,
        nickname=nickname,
    )


def _save_new_passkey(user: User, passkey: WebAuthnCredential) -> WebAuthnCredential:
    """Add a verified passkey to its account and commit it.

    The unique constraint on ``credential_id`` refuses a credential already saved, to this
    account or another, including one a second answer saved first; the loser gets a 409
    instead of a 500.

    Args:
        user: The account adding the passkey.
        passkey: The passkey to save.

    Returns:
        The saved passkey.

    Raises:
        DuplicateRecordError: If the credential is already registered.
    """
    try:
        user.passkeys.append(passkey)
        PASSKEY_AUDIT_TRAIL.log_created(passkey)
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise DuplicateRecordError(ALREADY_REGISTERED) from exc
    return passkey


def _check_registration(
    rp: RelyingParty, credential: dict[str, Any], challenge: bytes
) -> tuple[VerifiedRegistration, RegistrationCredential]:
    """Have py_webauthn check a registration answer, then build its public key.

    py_webauthn checks the challenge, the origin, the RP ID, and that the authenticator
    saw and verified its user. Hostile bytes can escape it as many exception types, and
    this touches no database, so any exception is a refusal. A ``none`` attestation
    leaves the public key unbuilt until a sign-in uses it, so it is built here, and a key
    cryptography refuses fails now rather than at every sign-in.

    Args:
        rp: The relying party.
        credential: The ``RegistrationResponseJSON`` that ``startRegistration`` returned.
        challenge: The challenge the registration options carried.

    Returns:
        What py_webauthn verified, and the parsed answer, which holds the transports.

    Raises:
        PasskeyError: If the answer does not verify.
    """
    try:
        parsed = parse_registration_credential_json(credential)
        verified = verify_registration_response(
            credential=parsed,
            expected_challenge=challenge,
            expected_rp_id=rp.id,
            expected_origin=rp.origin,
            require_user_verification=True,
        )
        public_key = decode_credential_public_key(verified.credential_public_key)
        decoded_public_key_to_cryptography(public_key)
    except Exception as exc:  # py_webauthn lets hostile bytes escape as many types
        _log.warning('A passkey registration was refused: %r', exc)
        raise PasskeyError(NOT_VERIFIED) from exc
    return verified, parsed


def verify_registration(
    user: User,
    rp: RelyingParty,
    credential: dict[str, Any],
    nickname: str | None,
    token: str | None,
) -> WebAuthnCredential:
    """Check the browser's answer to the registration options, then save the passkey.

    :func:`_check_registration` checks the answer. A credential id longer than WebAuthn
    allows is refused, and one already registered raises :class:`DuplicateRecordError`
    when it is saved. The route, not this, spends the challenge, by clearing its cookie.

    Args:
        user: The signed-in account adding the passkey.
        rp: The relying party.
        credential: The ``RegistrationResponseJSON`` that ``startRegistration`` returned.
        nickname: The passkey's name, or ``None``.
        token: The registration cookie's challenge token, or ``None`` without one.

    Returns:
        The saved passkey.

    Raises:
        PasskeyError: If the token is missing, expired, or issued to another account, or
            if the answer does not verify.
    """
    challenge = challenge_from_token('register', token, user_id=user.id)
    if challenge is None:
        raise PasskeyError(EXPIRED)
    verified, parsed = _check_registration(rp, credential, challenge)
    id_length = len(verified.credential_id)
    if id_length > MAX_CREDENTIAL_ID_BYTES:
        _log.warning('A passkey registration was refused: a %d-byte id', id_length)
        raise PasskeyError(NOT_VERIFIED)
    return _save_new_passkey(user, _new_passkey(verified, parsed, nickname))


def authentication_options(rp: RelyingParty) -> tuple[str, str]:
    """Build sign-in options for any of the site's passkeys, and sign their challenge.

    They name no credentials, so the browser offers every passkey it holds for the RP ID,
    in its own prompt or in the email field's autofill.

    Args:
        rp: The relying party.

    Returns:
        The options as JSON, for ``startAuthentication``, and the token that carries their
        challenge, for the sign-in cookie.
    """
    options = generate_authentication_options(
        rp_id=rp.id,
        timeout=CHALLENGE_TTL_SECONDS * 1000,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    token = new_challenge_token('login', options.challenge, user_id=None)
    return options_to_json(options), token


def _find_passkey(credential: AuthenticationCredential) -> WebAuthnCredential | None:
    """Find the saved passkey a sign-in answer comes from.

    The options named no credentials, so WebAuthn also requires the answer's user handle
    to be the passkey's account's.

    Args:
        credential: The parsed answer.

    Returns:
        The passkey, or ``None`` when none has the answer's credential id or the user
        handle belongs to another account.
    """
    passkey = (
        db.session.query(WebAuthnCredential)
        .filter_by(credential_id=credential.raw_id)
        .first()
    )
    if passkey is None or credential.response.user_handle != passkey.user.uuid.encode():
        return None
    return passkey


def verify_authentication(
    rp: RelyingParty, credential: dict[str, Any], token: str | None
) -> User | None:
    """Check a sign-in answer, then record the passkey's use.

    Every refusal looks the same to the caller, so an answer learns nothing about which
    passkeys exist. The authenticator must have verified its user, and a counter that
    does not move past the saved one is refused unless both are 0, which synced passkeys
    always report. The route, not this, spends the challenge, by clearing its cookie.

    Args:
        rp: The relying party.
        credential: The ``AuthenticationResponseJSON`` that ``startAuthentication``
            returned.
        token: The sign-in cookie's challenge token, or ``None`` without one.

    Returns:
        The passkey's account, or ``None`` when the token is missing or expired, no saved
        passkey matches, or the answer does not verify.
    """
    challenge = challenge_from_token('login', token, user_id=None)
    if challenge is None:
        return None
    try:
        parsed = parse_authentication_credential_json(credential)
        passkey = _find_passkey(parsed)
        if passkey is None:
            return None
        verified = verify_authentication_response(
            credential=parsed,
            expected_challenge=challenge,
            expected_rp_id=rp.id,
            expected_origin=rp.origin,
            credential_public_key=passkey.public_key,
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except _SIGN_IN_REJECTED as exc:
        _log.warning('A passkey sign-in was refused: %r', exc)
        return None
    passkey.sign_count = verified.new_sign_count
    passkey.backup_state = verified.credential_backed_up
    passkey.last_used_at = datetime.now(UTC)
    db.session.commit()
    return passkey.user


def list_passkeys(user: User) -> list[WebAuthnCredential]:
    """List an account's passkeys.

    Args:
        user: The account.

    Returns:
        Its passkeys, oldest first.
    """
    return sorted(user.passkeys, key=lambda passkey: passkey.id)


def _owned_passkey(user: User, passkey_id: int) -> WebAuthnCredential | None:
    """Find one of an account's passkeys, so another account's stays out of reach.

    Args:
        user: The account.
        passkey_id: The passkey's id from the URL.

    Returns:
        The passkey, or ``None`` if the account has none with that id.
    """
    return next((passkey for passkey in user.passkeys if passkey.id == passkey_id), None)


def rename_passkey(
    user: User, passkey_id: int, nickname: str | None
) -> WebAuthnCredential | None:
    """Change the name of one of an account's passkeys.

    Args:
        user: The signed-in account.
        passkey_id: The passkey's id.
        nickname: The new name, or ``None`` to clear it.

    Returns:
        The renamed passkey, or ``None`` if the account has no passkey with that id.
    """
    passkey = _owned_passkey(user, passkey_id)
    if passkey is None:
        return None
    before = PASSKEY_AUDIT_TRAIL.snapshot(passkey)
    passkey.nickname = nickname
    PASSKEY_AUDIT_TRAIL.log_updated(passkey, before)
    db.session.commit()
    return passkey


def delete_passkey(user: User, passkey_id: int) -> bool:
    """Delete one of an account's passkeys, unless it is the last way to sign in.

    :func:`~src_back.services.auth.lock_sign_in_methods` comes first, so a removal that
    overlaps this one finishes before the passkey is looked up and the methods counted,
    and :func:`~src_back.services.auth.require_another_sign_in_method` refuses the last
    one.

    Args:
        user: The signed-in account.
        passkey_id: The passkey's id.

    Returns:
        ``True`` once the passkey is gone, ``False`` if the account has none with that id.
    """
    lock_sign_in_methods(user)
    passkey = _owned_passkey(user, passkey_id)
    if passkey is None:
        return False
    require_another_sign_in_method(user)
    PASSKEY_AUDIT_TRAIL.log_deleted(passkey)
    user.passkeys.remove(passkey)
    db.session.commit()
    return True
