import json
import logging
import secrets
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from webauthn.helpers import bytes_to_base64url, encode_cbor

from src_back.models import AuditAction, AuditLog, User, WebAuthnCredential
from src_back.services import passkeys as passkey_service
from src_back.services.audit_log import audited_tables
from src_back.services.auth import LAST_METHOD
from src_back.services.errors import (
    DuplicateRecordError,
    LastSignInMethodError,
    PasskeyError,
)
from src_back.services.passkeys import (
    ALREADY_REGISTERED,
    CHALLENGE_TTL_SECONDS,
    EXPIRED,
    LOGIN_CHALLENGE_KEY,
    NOT_VERIFIED,
    REGISTER_CHALLENGE_KEY,
    RelyingParty,
    authentication_options,
    delete_passkey,
    list_passkeys,
    registration_options,
    rename_passkey,
    rp_settings,
    verify_authentication,
    verify_registration,
)
from src_back.tests.helpers import persist
from src_back.tests.software_authenticator import (
    ATTESTED_CREDENTIAL,
    BACKED_UP,
    BACKUP_ELIGIBLE,
    ES256,
    USER_PRESENT,
    USER_VERIFIED,
    SoftwareAuthenticator,
)

# An authenticator's answer to a ceremony's options.
Answer = Callable[[SoftwareAuthenticator, dict[str, Any]], dict[str, Any]]

# A P-256 key whose point, (1, 1), is not on the curve.
OFF_CURVE_KEY = encode_cbor(
    {1: 2, 3: ES256, -1: 1, -2: (1).to_bytes(32, 'big'), -3: (1).to_bytes(32, 'big')}
)

ZERO_AAGUID = '00000000-0000-0000-0000-000000000000'


@pytest.fixture()
def rp(app: Flask) -> Iterator[RelyingParty]:
    with app.test_request_context('/'):
        relying_party = rp_settings()
        assert relying_party is not None
        yield relying_party


def register(
    user: User, rp: RelyingParty, authenticator: SoftwareAuthenticator, **answer: Any
) -> WebAuthnCredential:
    options = json.loads(registration_options(user, rp))
    return verify_registration(user, rp, authenticator.create(options, **answer), None)


def sign_in(
    rp: RelyingParty, authenticator: SoftwareAuthenticator, **answer: Any
) -> User | None:
    options = json.loads(authentication_options(rp))
    return verify_authentication(rp, authenticator.get(options, **answer))


def committed_passkeys(db: SQLAlchemy) -> list[WebAuthnCredential]:
    # Only committed rows survive a rollback.
    db.session.rollback()
    return db.session.query(WebAuthnCredential).order_by(WebAuthnCredential.id).all()


def passkey_entry(db: SQLAlchemy) -> AuditLog:
    stmt = select(AuditLog).where(AuditLog.table_name == 'webauthn_credentials')
    return db.session.scalars(stmt).one()


# The relying party


def test_rp_settings_derive_from_the_public_base_url(
    app: Flask, rp: RelyingParty
) -> None:
    assert rp.id == 'app.test'
    assert rp.origin == 'https://app.test'
    # A developer's APP_NAME may set it.
    assert rp.name == app.config['WEBAUTHN_RP_NAME']


def test_rp_settings_name_the_site_after_webauthn_rp_name(app: Flask) -> None:
    app.config['WEBAUTHN_RP_NAME'] = 'Passkey check'
    with app.test_request_context('/'):
        relying_party = rp_settings()
    assert relying_party is not None
    assert relying_party.name == 'Passkey check'


@pytest.mark.parametrize(
    ('public_base_url', 'rp_id', 'origin'),
    [
        ('https://Example.COM', 'example.com', 'https://example.com'),
        ('https://example.com:443', 'example.com', 'https://example.com'),
        ('http://localhost:80', 'localhost', 'http://localhost'),
        ('http://localhost:5174', 'localhost', 'http://localhost:5174'),
        ('https://example.com:8443', 'example.com', 'https://example.com:8443'),
    ],
    ids=['upper-case', 'https-port', 'http-port', 'dev-port', 'other-port'],
)
def test_rp_settings_rebuild_the_origin_a_browser_reports(
    app: Flask, public_base_url: str, rp_id: str, origin: str
) -> None:
    app.config['PUBLIC_BASE_URL'] = public_base_url
    with app.test_request_context('/'):
        relying_party = rp_settings()
    assert relying_party is not None
    assert relying_party.id == rp_id
    assert relying_party.origin == origin


@pytest.mark.parametrize(
    'public_base_url', [None, 'localhost:5174'], ids=['unset', 'no-scheme']
)
def test_rp_settings_are_off_without_a_host(
    app: Flask, public_base_url: str | None
) -> None:
    app.config['PUBLIC_BASE_URL'] = public_base_url
    with app.test_request_context('/'):
        assert rp_settings() is None


@pytest.mark.parametrize(
    'public_base_url',
    ['http://localhost:abc', 'http://[::1:5174'],
    ids=['port-not-a-number', 'unclosed-bracket'],
)
def test_rp_settings_are_off_for_a_url_that_does_not_parse(
    app: Flask, public_base_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    app.config['PUBLIC_BASE_URL'] = public_base_url
    with (
        app.test_request_context('/'),
        caplog.at_level(logging.WARNING, logger='src_back.services.passkeys'),
    ):
        assert rp_settings() is None
    assert 'PUBLIC_BASE_URL is not a valid URL, so passkeys are off.' in caplog.text


# Registration options


def test_registration_options_ask_for_a_discoverable_passkey(
    user: User, rp: RelyingParty
) -> None:
    options = json.loads(registration_options(user, rp))
    assert options['rp'] == {'id': 'app.test', 'name': rp.name}
    assert options['user'] == {
        'id': bytes_to_base64url(user.uuid.encode()),
        'name': user.email,
        'displayName': user.email,
    }
    assert options['authenticatorSelection'] == {
        'residentKey': 'required',
        'requireResidentKey': True,
        'userVerification': 'required',
    }
    assert options['timeout'] == 300000
    assert options['attestation'] == 'none'
    assert options['excludeCredentials'] == []
    pending = session[REGISTER_CHALLENGE_KEY]
    assert pending['challenge'] == options['challenge']
    assert pending['user_id'] == user.id


def test_registration_options_exclude_the_accounts_passkeys(
    passkey_user: User, rp: RelyingParty, authenticator: SoftwareAuthenticator
) -> None:
    options = json.loads(registration_options(passkey_user, rp))
    assert options['excludeCredentials'] == [
        {
            'id': bytes_to_base64url(authenticator.credential_id),
            'type': 'public-key',
            'transports': ['internal', 'hybrid'],
        }
    ]


def test_registration_options_skip_a_transport_py_webauthn_no_longer_knows(
    user: User, rp: RelyingParty, authenticator: SoftwareAuthenticator
) -> None:
    passkey = authenticator.credential_for(user)
    passkey.transports = 'internal,teleport'
    persist(passkey)
    options = json.loads(registration_options(user, rp))
    assert options['excludeCredentials'] == [
        {
            'id': bytes_to_base64url(authenticator.credential_id),
            'type': 'public-key',
            'transports': ['internal'],
        }
    ]


# Registration


def test_verify_registration_saves_every_field(
    db: SQLAlchemy, user: User, rp: RelyingParty, authenticator: SoftwareAuthenticator
) -> None:
    options = json.loads(registration_options(user, rp))
    verify_registration(user, rp, authenticator.create(options), 'Laptop')
    [saved] = committed_passkeys(db)
    assert saved.credential_id == authenticator.credential_id
    assert saved.public_key == authenticator.cose_public_key()
    assert saved.sign_count == 0
    assert saved.transports == 'internal,hybrid'
    assert saved.aaguid == ZERO_AAGUID
    assert saved.backup_eligible is False
    assert saved.backup_state is False
    assert saved.nickname == 'Laptop'
    assert saved.user_id == user.id


def test_verify_registration_saves_the_authenticators_counter(
    db: SQLAlchemy, user: User, rp: RelyingParty
) -> None:
    # An authenticator that counts can start above 0; every other test registers at 0.
    register(user, rp, SoftwareAuthenticator(sign_count=7))
    [saved] = committed_passkeys(db)
    assert saved.sign_count == 7


@pytest.mark.parametrize(
    ('synced', 'flags', 'eligible', 'backed_up'),
    [
        (True, None, True, True),
        (
            False,
            USER_PRESENT | USER_VERIFIED | ATTESTED_CREDENTIAL | BACKUP_ELIGIBLE,
            True,
            False,
        ),
    ],
    ids=['synced', 'eligible-not-backed-up'],
)
def test_verify_registration_records_backup_eligibility_and_state(
    db: SQLAlchemy,
    user: User,
    rp: RelyingParty,
    flags: int | None,
    *,
    synced: bool,
    eligible: bool,
    backed_up: bool,
) -> None:
    register(user, rp, SoftwareAuthenticator(synced=synced), flags=flags)
    [saved] = committed_passkeys(db)
    assert saved.backup_eligible is eligible
    assert saved.backup_state is backed_up


def test_verify_registration_keeps_the_aaguid(
    db: SQLAlchemy, user: User, rp: RelyingParty
) -> None:
    aaguid = 'ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4'
    register(user, rp, SoftwareAuthenticator(aaguid=uuid.UUID(aaguid).bytes))
    [saved] = committed_passkeys(db)
    assert saved.aaguid == aaguid


def test_verify_registration_requires_user_verification(
    db: SQLAlchemy, user: User, rp: RelyingParty, authenticator: SoftwareAuthenticator
) -> None:
    # What a security key without a PIN answers.
    with pytest.raises(PasskeyError, match=NOT_VERIFIED):
        register(user, rp, authenticator, flags=USER_PRESENT | ATTESTED_CREDENTIAL)
    assert committed_passkeys(db) == []


@pytest.mark.parametrize(
    ('transports', 'saved'),
    [(['usb', 'usb', 'teleport', 'nfc'], 'usb,nfc'), ([], None)],
    ids=['repeated-and-unknown', 'none'],
)
def test_verify_registration_keeps_known_transports_once(
    db: SQLAlchemy,
    user: User,
    rp: RelyingParty,
    authenticator: SoftwareAuthenticator,
    transports: list[str],
    saved: str | None,
) -> None:
    register(user, rp, authenticator, transports=transports)
    assert [passkey.transports for passkey in committed_passkeys(db)] == [saved]


def test_verify_registration_needs_a_waiting_challenge(
    user: User, rp: RelyingParty
) -> None:
    with pytest.raises(PasskeyError, match=EXPIRED):
        verify_registration(user, rp, {}, None)


def test_verify_registration_refuses_an_expired_challenge(
    user: User, rp: RelyingParty, authenticator: SoftwareAuthenticator
) -> None:
    options = json.loads(registration_options(user, rp))
    session[REGISTER_CHALLENGE_KEY]['issued_at'] -= CHALLENGE_TTL_SECONDS + 1
    with pytest.raises(PasskeyError, match=EXPIRED):
        verify_registration(user, rp, authenticator.create(options), None)


def test_verify_registration_refuses_another_accounts_challenge(
    db: SQLAlchemy,
    user: User,
    admin_user: User,
    rp: RelyingParty,
    authenticator: SoftwareAuthenticator,
) -> None:
    options = json.loads(registration_options(admin_user, rp))
    with pytest.raises(PasskeyError, match=EXPIRED):
        verify_registration(user, rp, authenticator.create(options), None)
    assert committed_passkeys(db) == []


def test_verify_registration_spends_the_challenge(
    user: User, rp: RelyingParty, authenticator: SoftwareAuthenticator
) -> None:
    answer = authenticator.create(json.loads(registration_options(user, rp)))
    verify_registration(user, rp, answer, None)
    with pytest.raises(PasskeyError, match=EXPIRED):
        verify_registration(user, rp, answer, None)


REGISTRATIONS_THAT_DO_NOT_VERIFY: dict[str, Answer] = {
    'another-origin': lambda authenticator, options: authenticator.create(
        options, origin='https://evil.test'
    ),
    'another-rp-id': lambda authenticator, options: authenticator.create(
        {**options, 'rp': {**options['rp'], 'id': 'evil.test'}}
    ),
    'no-user-presence': lambda authenticator, options: authenticator.create(
        options, flags=USER_VERIFIED | ATTESTED_CREDENTIAL
    ),
    'backed-up-without-eligibility': lambda authenticator, options: authenticator.create(
        options, flags=USER_PRESENT | USER_VERIFIED | ATTESTED_CREDENTIAL | BACKED_UP
    ),
    'empty': lambda _authenticator, _options: {},
    'id-not-text': lambda _authenticator, _options: {'id': 1},
}


@pytest.mark.parametrize(
    'answer',
    REGISTRATIONS_THAT_DO_NOT_VERIFY.values(),
    ids=REGISTRATIONS_THAT_DO_NOT_VERIFY.keys(),
)
def test_verify_registration_refuses_an_answer_that_does_not_verify(
    db: SQLAlchemy,
    user: User,
    rp: RelyingParty,
    authenticator: SoftwareAuthenticator,
    answer: Answer,
) -> None:
    options = json.loads(registration_options(user, rp))
    with pytest.raises(PasskeyError, match=NOT_VERIFIED):
        verify_registration(user, rp, answer(authenticator, options), None)
    assert committed_passkeys(db) == []


def test_verify_registration_refuses_a_key_without_its_fields(
    user: User,
    rp: RelyingParty,
    authenticator: SoftwareAuthenticator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # py_webauthn reads the missing fields into a KeyError.
    monkeypatch.setattr(
        authenticator, 'cose_public_key', lambda: encode_cbor({1: 2, 3: -7})
    )
    with pytest.raises(PasskeyError, match=NOT_VERIFIED):
        register(user, rp, authenticator)


def test_verify_registration_refuses_a_key_that_is_not_a_map(
    user: User,
    rp: RelyingParty,
    authenticator: SoftwareAuthenticator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # py_webauthn indexes into it, an IndexError outside any exception list it documents.
    monkeypatch.setattr(authenticator, 'cose_public_key', lambda: encode_cbor([0, 2]))
    with pytest.raises(PasskeyError, match=NOT_VERIFIED):
        register(user, rp, authenticator)


def test_verify_registration_refuses_a_point_off_the_curve(
    db: SQLAlchemy,
    user: User,
    rp: RelyingParty,
    authenticator: SoftwareAuthenticator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # py_webauthn accepts it; only the service's own key build refuses it.
    monkeypatch.setattr(authenticator, 'cose_public_key', lambda: OFF_CURVE_KEY)
    with pytest.raises(PasskeyError, match=NOT_VERIFIED):
        register(user, rp, authenticator)
    assert committed_passkeys(db) == []


def test_verify_registration_caps_the_credential_id(
    db: SQLAlchemy, user: User, rp: RelyingParty
) -> None:
    # Random bytes, because PostgreSQL compresses an index value over about 510 bytes.
    too_long = SoftwareAuthenticator(credential_id=secrets.token_bytes(1024))
    with pytest.raises(PasskeyError, match=NOT_VERIFIED):
        register(user, rp, too_long)
    assert committed_passkeys(db) == []
    longest = SoftwareAuthenticator(credential_id=secrets.token_bytes(1023))
    register(user, rp, longest)
    saved = committed_passkeys(db)
    assert [passkey.credential_id for passkey in saved] == [longest.credential_id]


def test_verify_registration_logs_why_it_refused(
    user: User,
    rp: RelyingParty,
    authenticator: SoftwareAuthenticator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    options = json.loads(registration_options(user, rp))
    answer = authenticator.create(options, origin='https://evil.test')
    with (
        caplog.at_level(logging.WARNING, logger='src_back.services.passkeys'),
        pytest.raises(PasskeyError),
    ):
        verify_registration(user, rp, answer, None)
    refusal = 'A passkey registration was refused: InvalidRegistrationResponse('
    assert refusal in caplog.text
    assert 'https://evil.test' in caplog.text


def test_verify_registration_refuses_a_registered_credential(
    db: SQLAlchemy, user: User, rp: RelyingParty, authenticator: SoftwareAuthenticator
) -> None:
    register(user, rp, authenticator)
    with pytest.raises(DuplicateRecordError, match=ALREADY_REGISTERED):
        register(user, rp, authenticator)
    assert len(committed_passkeys(db)) == 1


def test_verify_registration_is_audited(
    db: SQLAlchemy, user: User, rp: RelyingParty, authenticator: SoftwareAuthenticator
) -> None:
    options = json.loads(registration_options(user, rp))
    passkey = verify_registration(user, rp, authenticator.create(options), 'Laptop')
    [saved] = committed_passkeys(db)
    assert saved is passkey
    entry = passkey_entry(db)
    assert entry.action is AuditAction.created
    assert entry.record_id == saved.id
    assert entry.record_label == 'Laptop'
    assert entry.changes == {
        'user_id': user.id,
        'nickname': 'Laptop',
        'aaguid': ZERO_AAGUID,
    }
    assert audited_tables()['webauthn_credentials'] is True


# Sign-in


def test_authentication_options_name_no_credentials(rp: RelyingParty) -> None:
    options = json.loads(authentication_options(rp))
    assert options['rpId'] == 'app.test'
    assert options['allowCredentials'] == []
    assert options['userVerification'] == 'required'
    assert options['timeout'] == 300000
    pending = session[LOGIN_CHALLENGE_KEY]
    assert pending['challenge'] == options['challenge']
    assert pending['user_id'] is None


def test_verify_authentication_records_the_use(
    db: SQLAlchemy,
    passkey_user: User,
    rp: RelyingParty,
    authenticator: SoftwareAuthenticator,
) -> None:
    assert sign_in(rp, authenticator) is passkey_user
    [passkey] = committed_passkeys(db)
    assert passkey.sign_count == 1
    assert passkey.backup_state is False
    last_used_at = passkey.last_used_at
    assert last_used_at is not None
    # SQLite reads it back without its offset.
    if last_used_at.tzinfo is None:
        last_used_at = last_used_at.replace(tzinfo=UTC)
    assert abs(datetime.now(UTC) - last_used_at) < timedelta(minutes=1)


def test_verify_authentication_follows_the_backup_state(
    db: SQLAlchemy, user: User, rp: RelyingParty
) -> None:
    authenticator = SoftwareAuthenticator(synced=True)
    persist(authenticator.credential_for(user))
    assert sign_in(rp, authenticator) is user
    [passkey] = committed_passkeys(db)
    assert passkey.backup_state is True


@pytest.mark.usefixtures('passkey_user')
def test_verify_authentication_requires_user_verification(
    rp: RelyingParty, authenticator: SoftwareAuthenticator
) -> None:
    assert sign_in(rp, authenticator, flags=USER_PRESENT) is None


def test_verify_authentication_accepts_a_counter_that_stays_at_zero(
    user: User, rp: RelyingParty
) -> None:
    # As synced passkeys always report.
    authenticator = SoftwareAuthenticator(counter_step=0)
    persist(authenticator.credential_for(user))
    assert sign_in(rp, authenticator) is user


def test_verify_authentication_refuses_a_counter_that_does_not_advance(
    db: SQLAlchemy, user: User, rp: RelyingParty
) -> None:
    authenticator = SoftwareAuthenticator(sign_count=5, counter_step=0)
    persist(authenticator.credential_for(user))
    assert sign_in(rp, authenticator) is None
    assert [passkey.sign_count for passkey in committed_passkeys(db)] == [5]


def test_verify_authentication_stores_the_largest_counter(
    db: SQLAlchemy, user: User, rp: RelyingParty
) -> None:
    authenticator = SoftwareAuthenticator(sign_count=2**32 - 2)
    persist(authenticator.credential_for(user))
    assert sign_in(rp, authenticator) is user
    # PostgreSQL's integer would refuse it.
    assert [passkey.sign_count for passkey in committed_passkeys(db)] == [4_294_967_295]


@pytest.mark.usefixtures('passkey_user')
def test_verify_authentication_refuses_an_unknown_passkey(rp: RelyingParty) -> None:
    assert sign_in(rp, SoftwareAuthenticator()) is None


@pytest.mark.parametrize(
    'user_handle',
    [bytes_to_base64url(b'someone-else'), None, 'A'],
    ids=['another-account', 'missing', 'not-base64url'],
)
@pytest.mark.usefixtures('passkey_user')
def test_verify_authentication_refuses_another_user_handle(
    rp: RelyingParty, authenticator: SoftwareAuthenticator, user_handle: str | None
) -> None:
    # 'A' is not base64url, so py_webauthn raises binascii.Error on it.
    answer = authenticator.get(json.loads(authentication_options(rp)))
    answer['response']['userHandle'] = user_handle
    assert verify_authentication(rp, answer) is None


def signed_by_another_key(
    authenticator: SoftwareAuthenticator, options: dict[str, Any]
) -> dict[str, Any]:
    answer = authenticator.get(options)
    another = SoftwareAuthenticator().get(options)
    answer['response']['signature'] = another['response']['signature']
    return answer


SIGN_INS_THAT_DO_NOT_VERIFY: dict[str, Answer] = {
    'another-origin': lambda authenticator, options: authenticator.get(
        options, origin='https://evil.test'
    ),
    'another-keys-signature': signed_by_another_key,
    'no-user-presence': lambda authenticator, options: authenticator.get(
        options, flags=USER_VERIFIED
    ),
    'empty': lambda _authenticator, _options: {},
    'empty-response': lambda _authenticator, _options: {
        'id': 'x',
        'rawId': 'x',
        'type': 'public-key',
        'response': {},
    },
}


@pytest.mark.parametrize(
    'answer',
    SIGN_INS_THAT_DO_NOT_VERIFY.values(),
    ids=SIGN_INS_THAT_DO_NOT_VERIFY.keys(),
)
@pytest.mark.usefixtures('passkey_user')
def test_verify_authentication_refuses_an_answer_that_does_not_verify(
    rp: RelyingParty, authenticator: SoftwareAuthenticator, answer: Answer
) -> None:
    options = json.loads(authentication_options(rp))
    assert verify_authentication(rp, answer(authenticator, options)) is None


def test_verify_authentication_refuses_a_saved_key_cryptography_refuses(
    user: User, rp: RelyingParty, authenticator: SoftwareAuthenticator
) -> None:
    passkey = authenticator.credential_for(user)
    passkey.public_key = OFF_CURVE_KEY
    persist(passkey)
    assert sign_in(rp, authenticator) is None


@pytest.mark.usefixtures('passkey_user')
def test_verify_authentication_lets_a_database_failure_through(
    rp: RelyingParty,
    authenticator: SoftwareAuthenticator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A database that fails must stay a 500, not pass for a refused passkey.
    def fail(_credential: object) -> None:
        raise OperationalError('SELECT', {}, Exception('the database is down'))

    monkeypatch.setattr(passkey_service, '_find_passkey', fail)
    with pytest.raises(OperationalError):
        sign_in(rp, authenticator)


def test_verify_authentication_needs_a_fresh_challenge(
    user: User, rp: RelyingParty
) -> None:
    # Its counter cannot refuse a replay, so only the spent challenge can.
    authenticator = SoftwareAuthenticator(counter_step=0)
    persist(authenticator.credential_for(user))

    answer = authenticator.get(json.loads(authentication_options(rp)))
    session.pop(LOGIN_CHALLENGE_KEY)
    assert verify_authentication(rp, answer) is None

    answer = authenticator.get(json.loads(authentication_options(rp)))
    session[LOGIN_CHALLENGE_KEY]['issued_at'] -= CHALLENGE_TTL_SECONDS + 1
    assert verify_authentication(rp, answer) is None

    answer = authenticator.get(json.loads(authentication_options(rp)))
    assert verify_authentication(rp, answer) is user
    assert verify_authentication(rp, answer) is None


# Upkeep


def test_list_passkeys_oldest_first(user: User) -> None:
    older = persist(SoftwareAuthenticator().credential_for(user))
    newer = persist(SoftwareAuthenticator().credential_for(user))
    # The collection holds them in whatever order the database returned them.
    user.passkeys.reverse()
    assert list_passkeys(user) == [older, newer]


def test_webauthn_credential_repr(app: Flask) -> None:
    passkey = WebAuthnCredential(id=4, user_id=3)
    assert repr(passkey) == '<WebAuthnCredential 4 user=3>'


def test_rename_passkey_changes_the_nickname_and_is_audited(
    db: SQLAlchemy, passkey_user: User
) -> None:
    passkey = passkey_user.passkeys[0]
    assert rename_passkey(passkey_user, passkey.id, 'Phone') is passkey
    assert [saved.nickname for saved in committed_passkeys(db)] == ['Phone']
    entry = passkey_entry(db)
    assert entry.action is AuditAction.updated
    assert entry.record_label == 'Phone'
    assert entry.changes == {'nickname': {'old': None, 'new': 'Phone'}}


def test_rename_passkey_to_the_same_name_logs_nothing(
    db: SQLAlchemy, passkey_user: User
) -> None:
    passkey_id = passkey_user.passkeys[0].id
    rename_passkey(passkey_user, passkey_id, 'Phone')
    rename_passkey(passkey_user, passkey_id, 'Phone')
    db.session.rollback()
    assert passkey_entry(db).changes == {'nickname': {'old': None, 'new': 'Phone'}}


def test_rename_passkey_ignores_another_accounts_passkey(
    db: SQLAlchemy, passkey_user: User, user: User
) -> None:
    passkey_id = passkey_user.passkeys[0].id
    assert rename_passkey(user, passkey_id, 'Mine now') is None
    assert [saved.nickname for saved in committed_passkeys(db)] == [None]


def test_delete_passkey_removes_it_and_is_audited(
    db: SQLAlchemy, user: User, authenticator: SoftwareAuthenticator
) -> None:
    passkey_id = persist(authenticator.credential_for(user)).id
    assert delete_passkey(user, passkey_id) is True
    assert committed_passkeys(db) == []
    entry = passkey_entry(db)
    assert entry.action is AuditAction.deleted
    assert entry.record_id == passkey_id
    assert entry.changes == {'user_id': user.id, 'nickname': None, 'aaguid': None}


def test_delete_passkey_ignores_another_accounts_passkey(
    db: SQLAlchemy, passkey_user: User, user: User
) -> None:
    passkey_id = passkey_user.passkeys[0].id
    assert delete_passkey(user, passkey_id) is False
    assert [saved.id for saved in committed_passkeys(db)] == [passkey_id]


def test_delete_passkey_refuses_the_last_way_to_sign_in(
    db: SQLAlchemy, passkey_user: User
) -> None:
    passkey_id = passkey_user.passkeys[0].id
    with pytest.raises(LastSignInMethodError, match=LAST_METHOD):
        delete_passkey(passkey_user, passkey_id)
    assert [saved.id for saved in committed_passkeys(db)] == [passkey_id]
    assert db.session.query(AuditLog).count() == 0
