# Issue #32: Add passkeys (WebAuthn) for sign-in and account management

## Context

Accounts sign in with a password or, since #29, with Google. This change adds passkeys
(WebAuthn), with `webauthn` (py_webauthn) on the server and `@simplewebauthn/browser` in
the browser. A signed-out visitor signs in with a passkey from a button on the sign-in
page, or from the email field's autofill suggestion, without typing an email. A signed-in
account adds, renames, and deletes its passkeys in a new section of the Account page. A
passkey counts as a sign-in method, so deleting an account's last way in is refused, and
unlinking Google is allowed while a passkey remains.

Issues #28 and #29 built what this reuses: `complete_login()`,
`count_sign_in_methods()`, and `require_another_sign_in_method()` in
`src_back/services/auth.py`; `LastSignInMethodError` and `LAST_METHOD`;
`PUBLIC_BASE_URL`, with its development fallback and the startup warning that passkeys
are off without it; `WEBAUTHN_RP_NAME` in `src_back/app.py`, `.env.example`, and
`.env.staging.example`; the `passwordless_user` and `linked_user` fixtures; the Account
page; and the admin-only audit trail for sign-in methods (`OAUTH_ACCOUNT_AUDIT_TRAIL`).
Nothing on the WebAuthn side exists yet: no table, service, route, dependency, or frontend
module.

### Where the issue and the code disagree

1. **A 401 from the Account page's passkey calls ends the session.** The issue says the
   client "already suppresses the lost-session handler for `/v1/auth/` URLs", which is
   true and is the problem: `reportLostSession` in `src_front/src/api/client.ts:100-104`
   exempts every `/v1/auth/` URL but `/v1/auth/oauth/`, so an expired session on the
   Account page would show "Unauthorized" in the list instead of returning to `/login`.
   #29 hit the same thing (its departure 8). Only `/v1/auth/passkeys/login/` keeps the
   exemption. The list URL is `/v1/auth/passkeys`, without a trailing slash, because the
   routes use `@bp.get('')` as `src_back/api/users.py:25` does, so the test matches the
   path itself as well as its subpaths.
2. **The two options endpoints are GETs.** Host nginx counts every POST under
   `/api/v1/auth/` against a burst of six
   (`scripts/nginx-ssl.conf.template:12-16, 67-69`). The sign-in page's autofill asks for
   options on every visit, so as POSTs they would spend one of the six before the visitor
   tried anything, and a passkey sign-in would cost two. As GETs, a passkey sign-in
   spends one POST, `/login/verify`. Each answer carries `Cache-Control: no-store`.
   Chuck's choice is recorded below.
3. **`sign_count` is a `BigInteger`.** WebAuthn's counter is an unsigned 32-bit number,
   and PostgreSQL's `integer` stops at 2,147,483,647, so a large counter would be a 500 on
   PostgreSQL and pass on SQLite. A test stores 4,294,967,295, and CI runs it on
   PostgreSQL.
4. **The registration challenge names its account.** `session['passkey_register']` holds
   the account id beside the challenge, and verifying refuses another account's challenge.
   Without it, an account that asked for options, then a second account that signed in in
   the same browser, would register a passkey whose user handle is the first account's
   `uuid`, which then never signs in.
5. **A deactivated account's passkey answers 403.** The issue's table lists 401 and 422
   for `/login/verify`; `complete_login` raises `InactiveAccountError`, which the route
   answers with 403 `Account is inactive.`, after the passkey checked out, as password
   login does.
6. **The expected origin is normalized.** `PUBLIC_BASE_URL` is used verbatim for OAuth,
   but a browser reports an origin with a lowercase host and without a default port, so
   `https://Example.com:443` would fail every passkey. `rp_settings()` rebuilds the origin
   from the parsed URL, and a value that does not parse, such as one whose port is not a
   number, turns passkeys off with a warning instead of a 500 on every route. The #28
   plan left startup validation of `PUBLIC_BASE_URL` for #32 to consider
   (`plans/archive/pr-42-normalize-emails-allow-passwordless.md:1488`); normalizing at use
   needs no validation.
7. **`PasskeyError` (400) joins `services/errors.py`.** It carries the refusal of a
   registration answer, expired or unverifiable, to the route, which answers
   `bad_request(str(exc))`, as `SelfModificationError` is answered.
8. **The tests split by module.** The repository keeps one test file per module, so the
   service is tested in `test_passkeys.py` and the routes in `test_passkeys_api.py`, as
   `test_oauth.py` and `test_oauth_api.py` split #29. The frontend tests mirror `src/`
   (`test/api/passkeys.test.ts`, not `passkeysApi.test.ts`).
9. **A cancelled prompt changes nothing.** `handleAuthAction` in
   `src_front/src/hooks/useAuthFormState.ts` takes an action that may resolve `null`,
   which means the visitor cancelled or a newer ceremony replaced this one: no error and
   no navigation. A cancelled browser prompt otherwise surfaces as an error whose message
   points at the WebAuthn specification.
10. **The sign-in page gets `SignInOptions`.** `Login()` is already 49 lines against the
    50-line cap, so the passkey button and the autofill live in
    `src_front/src/components/auth/SignInOptions.tsx`, which shows the "or" divider, the
    passkey button, and the provider links. `ProviderButtons` keeps the Register page as
    it is, and both render the links through a shared `ProviderLinks`.
11. **The autofill renews itself.** A conditional request never times out (WebAuthn Level
    3, section 5.1.4.1, sets its timer to the document's lifetime), but its challenge
    expires after five minutes, so the offer fetches new options every four minutes, at
    once after a passkey picked from it fails, and again once the button's sign-in
    settles. It calls `handleAuthAction` only after a pick, because that clears the
    page's error, and a renewal must not erase a message that just appeared. The button
    ends the offer first, even one whose options are still loading, because starting a
    ceremony aborts the one before it, and a late offer would otherwise abort the
    button's prompt.
12. **The effect reads `handleAuthAction` through a ref.** `eslint-plugin-react-hooks` 5
    predates `useEffectEvent`, and CI fails on its `exhaustive-deps` warning, so the hook
    keeps the latest callback in a ref that an effect updates, the pattern before
    `useEffectEvent`.
13. **The Passkeys section is a `RecordSection`, and #57's crash is fixed here.**
    `ai/conventions.md` makes a list with create, edit, and delete dialogs a
    `RecordSection`, and the passkey list is the first to pass `remove`, which crashes
    every production build until `RecordDeleteDialog` stops reading `item!.id` in its
    closure. This change applies #57's first fix; its second, a CI check of the compiled
    build, stays in #57, which stays open. Chuck's choice is recorded below.
14. **Passkeys are audited, admin-only.** A trail on `webauthn_credentials` logs each
    add, rename, and delete, as #29 logs provider links; a sign-in changes only fields the
    trail does not record. Admin-only is required, not a matter of taste:
    `list_record_history` (`src_back/api/audit_logs.py:35-57`) serves any signed-in
    account the history of a table that is not admin-only, so anyone could read other
    accounts' nicknames, AAGUIDs, and user ids at
    `?table=webauthn_credentials&record_id=N`. Chuck's choice is recorded below.
15. **User verification is required.** The issue makes it preferred, so a security key
    without a PIN would sign in on possession alone, which WebAuthn Level 3 warns leaves
    a user "particularly vulnerable to theft of the authenticator", and
    `@simplewebauthn/server` 14 requires it at sign-in by default. Both options ask for
    it, and both verify calls pass `require_user_verification=True`. Chuck's choice is
    recorded below.
16. **Credential ids are capped at 1,023 bytes.** WebAuthn Level 3, section 7.1, says a
    longer id should fail registration, and py_webauthn does not check it. PostgreSQL's
    B-tree caps an index entry near 2.7 KB and refuses a longer one with
    `ProgramLimitExceeded`, an `OperationalError` that the `IntegrityError` branch misses,
    so a signed-in account posting a 3 KB id would get a 500.
17. **A registration answer that raises anything is refused.** py_webauthn lets hostile
    bytes escape registration as `IndexError`, `AttributeError`, `KeyError`, `TypeError`,
    `ValueError`, and cryptography's `UnsupportedAlgorithm`, and that block touches no
    database, so `verify_registration` catches `Exception`. A sign-in answer escapes only
    as `ValueError`, and its block queries the database, so it catches
    `(WebAuthnException, ValueError)` and lets a database failure stay a 500. Both log
    the refusal with `%r`, because py_webauthn's messages quote what the client sent.

### Decisions made with Chuck

Chuck took each recommendation, the first three on 2026-11-02 and the fourth on
2026-11-03, after the review raised it:

- The options endpoints are GETs, not the issue's POSTs (departure 2).
- The Passkeys section is a `RecordSection`, with #57's first fix applied here and #57
  left open for its CI check (departure 13).
- Passkey adds, renames, and deletes are audited in an admin-only trail (departure 14).
- Both ceremonies require user verification (departure 15).

### Primary-source checks

Read on 2026-11-02 from the published packages and their tagged source, not from memory:

- `webauthn` 3.0.1 (PyPI, 2026-09-25) is the latest. It needs Python 3.10 or later and
  brings `cbor2>=6.1.2`, `cryptography>=49`, `pyOpenSSL>=26.3.0`, `pyasn1`, and
  `pyasn1-modules`; the issue leaves out the last. The venv's cryptography 50.0.2
  satisfies it, and pyOpenSSL 26.4 caps cryptography below 51. cbor2 6 is a Rust
  extension with wheels for macOS on Apple silicon, glibc 2.28 and later, musl, and
  Windows: the backend image (`python:3.12-slim`, now Debian trixie) and CI take a
  wheel, and an Intel Mac would need Rust.
- 3.0.0 cut the default algorithms to EdDSA, ES256, and RS256. Every ceremony function is
  keyword-only. `options_to_json()` returns a `str`, so the routes send it as the body;
  `jsonify()` would encode it twice. `VerifiedRegistration.aaguid` is a `str` in UUID
  form, and `credential_device_type` is `CredentialDeviceType.MULTI_DEVICE` when the
  authenticator set backup eligibility. A backed-up flag without eligibility raises
  `InvalidBackupFlags`.
- Every py_webauthn exception subclasses `WebAuthnException`, but hostile input escapes
  as others. At registration the key is decoded and the attestation formats run outside
  any `try`: a key that is not a map raises `IndexError` or `AttributeError`, one without
  its fields `KeyError` or `TypeError`, and a `packed` certificate with an unknown key
  type cryptography's `UnsupportedAlgorithm`. At sign-in only `ValueError` escapes: a
  user handle that is not base64url (`binascii.Error`) and a saved key cryptography
  refuses. Departure 17 follows from this.
- py_webauthn checks that a credential id is present but not its length, and WebAuthn
  Level 3, section 7.1, says one over 1,023 bytes should fail registration.
- A `none` attestation never builds the public key, so a point off the curve registers and
  fails only at the first sign-in. `verify_registration` builds the key itself and refuses
  such a passkey with a 400.
- The origin check is exact string equality, and `http://localhost:<port>` with the RP ID
  `localhost` passes; py_webauthn's own tests use that pair. The sign-count check refuses
  a counter that is not above the saved one unless both are 0, and runs before the
  signature check.
- `parse_registration_credential_json()` drops transports it does not know and keeps
  repeats; `parse_authentication_credential_json()` gives the user handle as bytes, or
  `None` without one. Neither verified result carries the user handle, so the service
  compares it.
- `@simplewebauthn/browser` 14.0.0 (npm, 2026-09-02) is the latest. It has no
  dependencies and ships ESM and CommonJS; its minified bundle is 13.5 KB, 3.8 KB gzipped,
  where the issue says about 10 KB. Importing it touches no browser global, so jsdom tests
  can import it. `PublicKeyCredentialCreationOptionsJSON`,
  `PublicKeyCredentialRequestOptionsJSON`, `RegistrationResponseJSON`, and
  `AuthenticationResponseJSON` are exported from the package itself, as types only.
- A dismissed or timed-out prompt rejects with a `WebAuthnError` whose `name` is
  `NotAllowedError` and whose `code` is `ERROR_PASSTHROUGH_SEE_CAUSE_PROPERTY`. An abort,
  by `WebAuthnAbortService.cancelCeremony()` or by a newer ceremony, has the code
  `ERROR_CEREMONY_ABORTED`. A passkey the exclude list names gives
  `ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED`. Starting a ceremony aborts the one before
  it. `startAuthentication({ useBrowserAutofill: true })` rejects with a plain `Error`
  when the browser lacks conditional mediation or the page has no
  `input[autocomplete$='webauthn']`.
- SimpleWebAuthn's own example server at v14.0.0 serves both options routes as GETs and
  keeps the challenge in the session (`example/index.ts:109,215`).
- Chrome refuses WebAuthn on a page with a certificate error, so the browser check below
  uses `http://localhost`, which is a secure context, rather than a self-signed https
  origin as #29's did.

### Sources

- [py_webauthn 3.0.1 on PyPI](https://pypi.org/project/webauthn/3.0.1/) and
  [its source at v3.0.1](https://github.com/duo-labs/py_webauthn/tree/v3.0.1)
- [@simplewebauthn/browser on npm](https://www.npmjs.com/package/@simplewebauthn/browser)
  and [its 14.0.0 files](https://unpkg.com/browse/@simplewebauthn/browser@14.0.0/)
- [WebAuthn Level 3, verifying an authentication assertion][webauthn-assertion]
- [passkeys.dev device support](https://passkeys.dev/device-support/)
- [Chrome DevTools, emulate authenticators][devtools-webauthn]

[webauthn-assertion]: https://www.w3.org/TR/webauthn-3/#sctn-verifying-assertion
[devtools-webauthn]: https://developer.chrome.com/docs/devtools/webauthn

### Accepted limits

- Flask's session is a signed cookie, not a server-side store. Whoever holds both a
  visitor's session cookie and an answer that browser just sent can replay the answer
  until its challenge expires, five minutes on. The counter check stops that for an
  authenticator that counts, but synced passkeys report 0. Both halves leave the browser
  only over TLS. A server-side record of spent challenges, such as a table a scheduled job
  sweeps, would close it; the session costs no write per sign-in.
- Adding a passkey asks for no password or other fresh proof, as linking a provider does
  not (#29). A stolen session can add a passkey that survives a password change, so the
  compromised-account steps in `ai/auth.md` gain the passkeys, and #44's session
  revocation would end the stolen session.
- An account whose only way in is a passkey on a lost device cannot sign in until an admin
  sets a password for it on the Users screen. The issue's follow-up, a set-password route
  for passwordless accounts, stays a follow-up.
- Moving the site to another domain changes the RP ID and orphans every passkey. Staging's
  copy of production's passkeys never works for the same reason.
- Two sign-in tabs share one session, so the second tab's challenge replaces the first's,
  and a passkey picked in the first tab fails once.
- Admins see no passkeys on the Users screen; the audit log is where they show.
- A security key without a PIN must be given one before it can hold a passkey here;
  Chrome offers to create it, and otherwise the key maker's tool sets it. Phones, Macs,
  and Windows Hello always verify.
- A passkey picked from the email field's suggestions and then dismissed at the device's
  own prompt leaves the suggestions empty until the next renewal, up to four minutes; the
  button works meanwhile.
- A renewal that lands while the visitor answers the device's prompt for a picked passkey
  aborts that pick, which shows nothing; the next pick works.
- A deactivated account's refused sign-in still records its passkey's counter, backup
  state, and `last_used_at`, since the answer verified before `complete_login` refused it.
- While the sign-in page stays open, it fetches new options every four minutes.

## Branch

`issue-32-add-passkeys-webauthn-for-sign-in-and`, already checked out; PR #59 exists.

## Change

**Backend, new**: `src_back/models/webauthn_credential.py`, the migration
`migrations/versions/2026_11_<DD>_<rev>_webauthn_credentials.py`,
`src_back/schemas/passkeys.py`, `src_back/services/passkeys.py`,
`src_back/api/passkeys.py`, `src_back/tests/software_authenticator.py`,
`src_back/tests/test_passkeys.py`, `src_back/tests/test_passkeys_api.py`.

**Backend, edited**: `requirements.txt`, `src_back/models/__init__.py`,
`src_back/models/user.py`, `src_back/services/errors.py`, `src_back/services/auth.py`,
`src_back/api/__init__.py`, `src_back/app.py`, `src_back/tests/conftest.py`,
`src_back/tests/test_auth.py`, `src_back/tests/test_oauth_api.py`,
`src_back/tests/test_schemas.py`.

**Frontend, new**: `src_front/src/api/passkeys.ts`, `src_front/src/utils/passkeys.ts`,
`src_front/src/schemas/passkey.ts`, `src_front/src/hooks/passkeys.ts`,
`src_front/src/hooks/usePasskeyLogin.ts`,
`src_front/src/components/auth/SignInOptions.tsx`,
`src_front/src/components/account/Passkeys.tsx`, `src_front/src/test/utils/webauthn.ts`,
`src_front/src/test/utils/webauthnMock.ts`, and their tests under `src_front/src/test/`
at the mirrored paths.

**Frontend, edited**: `package.json`, `package-lock.json`, `src_front/src/types/auth.ts`,
`src_front/src/api/client.ts`, `src_front/src/hooks/useAuthFormState.ts`,
`src_front/src/components/auth/ProviderButtons.tsx`, `src_front/src/pages/Login.tsx`,
`src_front/src/pages/Account.tsx`, `src_front/src/components/common/RecordSection.tsx`,
`src_front/src/components/common/EntityList.tsx` (added during implementation),
`src_front/src/test/utils/fixtures.ts`, `src_front/src/test/App.test.tsx`, and the tests
of each edited module.

**Documentation**: `ai/auth.md`, `ai/domain.md`, `ai/project.md`, `ai/conventions.md`,
`ai/staging.md`, `tools.md`, `README.md`.

### `requirements.txt` — the server library

After `joserfc==1.7.7`:

```text
# Passkeys (ai/auth.md). It brings cbor2, cryptography, pyOpenSSL, pyasn1, and
# pyasn1-modules.
webauthn==3.0.1
```

Then `.venv/bin/python -m pip install -r requirements-dev.txt`.

### `src_back/models/webauthn_credential.py` — new

```python
"""A passkey: a WebAuthn credential that can sign in to one account."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src_back.extensions import Base
from src_back.models.base import BaseMixin

if TYPE_CHECKING:
    from src_back.models.user import User


class WebAuthnCredential(BaseMixin, Base):
    """One passkey, held by an authenticator, that can sign in to one account.

    ``credential_id`` is what the browser names at sign-in, and ``public_key`` the COSE
    key that checks the signature; neither leaves the server. ``sign_count`` is the
    authenticator's counter, which a cloned key would repeat; synced passkeys always
    report 0. It is a ``BigInteger`` because the counter is an unsigned 32-bit number,
    which PostgreSQL's ``integer`` cannot hold. ``transports`` keeps the browser's hints,
    comma-joined, for the next registration's exclude list; ``backup_eligible`` says
    whether the passkey can sync, and ``backup_state`` whether it has.
    """

    __tablename__ = 'webauthn_credentials'

    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), index=True
    )
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(BigInteger, default=0)
    transports: Mapped[str | None] = mapped_column(String(255))
    aaguid: Mapped[str | None] = mapped_column(String(36))
    backup_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_state: Mapped[bool] = mapped_column(Boolean, default=False)
    nickname: Mapped[str | None] = mapped_column(String(64))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates='passkeys')

    def __repr__(self) -> str:
        """Describe the passkey by id and account for logs and debugging.

        Returns:
            The repr string, for example ``<WebAuthnCredential 4 user=3>``.
        """
        return f'<WebAuthnCredential {self.id} user={self.user_id}>'
```

### `src_back/models/user.py` and `src_back/models/__init__.py` — the relationship

In `user.py`, add `from src_back.models.webauthn_credential import WebAuthnCredential`
under the `TYPE_CHECKING` imports, and below `oauth_accounts`:

```python
    passkeys: Mapped[list['WebAuthnCredential']] = relationship(
        back_populates='user', cascade='all, delete-orphan'
    )
```

In the class docstring, "``oauth_accounts`` holds the providers it can sign in with"
becomes "``oauth_accounts`` holds the providers it can sign in with, and ``passkeys`` its
passkeys".

In `__init__.py`, import `WebAuthnCredential` from `src_back.models.webauthn_credential`
after the `user` import, and write `__all__` one name per line, since the eighth name
takes it past 90 characters:

```python
__all__ = [
    'AuditAction',
    'AuditLog',
    'BaseMixin',
    'OAuthAccount',
    'Role',
    'User',
    'WebAuthnCredential',
]
```

### `migrations/versions/2026_11_<DD>_<rev>_webauthn_credentials.py` — new

Generate it with `.venv/bin/flask --app src_back.app db migrate -m "webauthn credentials"`
and keep Alembic's layout, as `2026_11_02_bdf3bdb0b9e8_oauth_accounts.py` does. Review it
against this; `down_revision` is `'bdf3bdb0b9e8'`:

```python
def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('webauthn_credentials',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('credential_id', sa.LargeBinary(), nullable=False),
    sa.Column('public_key', sa.LargeBinary(), nullable=False),
    sa.Column('sign_count', sa.BigInteger(), nullable=False),
    sa.Column('transports', sa.String(length=255), nullable=True),
    sa.Column('aaguid', sa.String(length=36), nullable=True),
    sa.Column('backup_eligible', sa.Boolean(), nullable=False),
    sa.Column('backup_state', sa.Boolean(), nullable=False),
    sa.Column('nickname', sa.String(length=64), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uuid', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('credential_id'),
    sa.UniqueConstraint('uuid')
    )
    op.create_index(
        op.f('ix_webauthn_credentials_user_id'),
        'webauthn_credentials',
        ['user_id'],
        unique=False,
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        op.f('ix_webauthn_credentials_user_id'), table_name='webauthn_credentials'
    )
    op.drop_table('webauthn_credentials')
    # ### end Alembic commands ###
```

### `src_back/services/errors.py` — `PasskeyError`

After `OAuthError`:

```python
class PasskeyError(Exception):
    """A passkey's registration answer expired or did not verify (400)."""
```

### `src_back/services/auth.py` — passkeys count

In `complete_login`'s docstring, "registration, password login, and a provider callback
now, a passkey later" becomes "registration, password login, a provider callback, and a
passkey". `count_sign_in_methods` becomes:

```python
def count_sign_in_methods(user: User) -> int:
    """Count the ways an account can sign in.

    A password, each linked provider, and each passkey count.

    Args:
        user: The account to inspect.

    Returns:
        The number of sign-in methods the account has.
    """
    providers_and_passkeys = len(user.oauth_accounts) + len(user.passkeys)
    return (1 if user.has_password else 0) + providers_and_passkeys
```

### `src_back/schemas/passkeys.py` — new

`fields.Dict` takes the browser's answer whole: py_webauthn parses it and refuses
anything malformed. The nickname is trimmed in `@pre_load`, as `ai/conventions.md`
requires, so a padded name of the maximum length passes. The schemas are the first to
trim, so `_NicknameSchema` is the pattern.

```python
"""Serialization of passkeys, and validation of the ceremony and rename payloads."""

from typing import Any

from marshmallow import Schema, fields, pre_load, validate

from src_back.models import WebAuthnCredential
from src_back.schemas.base import BaseSchema

NICKNAME_RULE = validate.Length(max=64, error='Use 64 characters or fewer.')


class PasskeySchema(BaseSchema):
    """Serialize a passkey for its owner.

    Every field is dump-only: the registration ceremony creates a passkey, and only its
    nickname changes after, through :class:`PasskeyRenameSchema`. The credential id, the
    public key, and the counter stay out, since the client has no use for them, and an
    auto schema leaves out ``user_id``.
    """

    class Meta(BaseSchema.Meta):
        """Bind to the ``webauthn_credentials`` table and hide the key material."""

        model = WebAuthnCredential
        exclude = ('credential_id', 'public_key', 'sign_count')
        dump_only = (
            *BaseSchema.AUDIT,
            'nickname',
            'transports',
            'aaguid',
            'backup_eligible',
            'backup_state',
            'last_used_at',
        )


class _NicknameSchema(Schema):
    """Trim a payload's nickname before its length rule runs; a blank one becomes null."""

    @pre_load
    def _trim_nickname(self, data: object, **_kwargs: Any) -> object:
        """Trim the nickname, so a padded name of the maximum length still passes.

        Args:
            data: The payload as the client sent it.
            **_kwargs: What marshmallow passes every hook, such as ``many``. Unused.

        Returns:
            The payload with its nickname trimmed, or ``None`` when the trim leaves
            nothing; any other payload unchanged, for validation to refuse.
        """
        if isinstance(data, dict) and isinstance(data.get('nickname'), str):
            return {**data, 'nickname': data['nickname'].strip() or None}
        return data


class PasskeyRegisterSchema(_NicknameSchema):
    """Validate the answer to the registration options, with an optional nickname."""

    credential = fields.Dict(required=True)
    nickname = fields.String(load_default=None, allow_none=True, validate=NICKNAME_RULE)


class PasskeyAssertionSchema(Schema):
    """Validate the answer to the sign-in options."""

    credential = fields.Dict(required=True)


class PasskeyRenameSchema(_NicknameSchema):
    """Validate a passkey's new nickname; null or a blank one clears it."""

    nickname = fields.String(required=True, allow_none=True, validate=NICKNAME_RULE)


passkey_schema = PasskeySchema()
passkey_register_schema = PasskeyRegisterSchema()
passkey_assertion_schema = PasskeyAssertionSchema()
passkey_rename_schema = PasskeyRenameSchema()
```

### `src_back/services/passkeys.py` — new

The ceremonies, the challenges, and the upkeep. `rp_settings()` returns `None` without a
host, and every route checks it first. Each function stays under 50 lines, docstring
included.

```python
"""Passkeys: the WebAuthn ceremonies that add one and sign in with one, and their upkeep.

The relying party is the site at ``PUBLIC_BASE_URL``, so passkeys are off without it.
Each ceremony's challenge waits in the Flask session until its answer arrives, which works
because every passkey call is a same-site request; ``ai/auth.md`` explains the flow and
what the session does not defend against.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from flask import current_app, session
from sqlalchemy.exc import IntegrityError
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import (
    base64url_to_bytes,
    bytes_to_base64url,
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
from src_back.services.auth import require_another_sign_in_method
from src_back.services.errors import DuplicateRecordError, PasskeyError

_log = logging.getLogger(__name__)

CHALLENGE_TTL_SECONDS = 300
"""How long a ceremony's challenge stays good; the browser's prompt waits as long."""

REGISTER_CHALLENGE_KEY = 'passkey_register'
"""The session key of a waiting registration challenge."""

LOGIN_CHALLENGE_KEY = 'passkey_login'
"""The session key of a waiting sign-in challenge."""

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


def _store_challenge(key: str, challenge: bytes, *, user_id: int | None) -> None:
    """Keep a ceremony's challenge in the session until its answer arrives.

    Args:
        key: The session key for this kind of ceremony.
        challenge: The random bytes the options carry.
        user_id: The account the options were built for, or ``None`` for a sign-in.
    """
    session[key] = {
        'challenge': bytes_to_base64url(challenge),
        'issued_at': time.time(),
        'user_id': user_id,
    }


def _take_challenge(key: str, *, user_id: int | None) -> bytes | None:
    """Take a ceremony's challenge out of the session, so one answer spends it.

    Args:
        key: The session key for this kind of ceremony.
        user_id: The account answering, or ``None`` for a sign-in.

    Returns:
        The challenge, or ``None`` when none is waiting, it is older than
        :data:`CHALLENGE_TTL_SECONDS`, or it was issued to another account.
    """
    pending = session.pop(key, None)
    if not isinstance(pending, dict) or pending.get('user_id') != user_id:
        return None
    if time.time() - pending['issued_at'] > CHALLENGE_TTL_SECONDS:
        return None
    return base64url_to_bytes(pending['challenge'])


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


def registration_options(user: User, rp: RelyingParty) -> str:
    """Build the options for adding a passkey, and keep their challenge.

    The passkey must be discoverable, so it can sign in without an email, and must verify
    its user, with a biometric, a screen lock, or a PIN. The account's ``uuid`` is its
    user handle, which says nothing about the person. Each passkey the account has is
    excluded, so a device that holds one says so instead of making a second.

    Args:
        user: The signed-in account adding a passkey.
        rp: The relying party.

    Returns:
        The options as JSON, for ``startRegistration``.
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
    _store_challenge(REGISTER_CHALLENGE_KEY, options.challenge, user_id=user.id)
    return options_to_json(options)


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


def verify_registration(
    user: User, rp: RelyingParty, credential: dict[str, Any], nickname: str | None
) -> WebAuthnCredential:
    """Check the browser's answer to the registration options, then save the passkey.

    py_webauthn checks the challenge, the origin, the RP ID, and that the authenticator
    saw and verified its user. Hostile bytes can escape it as many exception types, and
    this block touches no database, so any exception is a refusal. A ``none``
    attestation leaves the public key unbuilt until a sign-in uses it, so it is built
    here, and a key cryptography refuses fails now rather than at every sign-in. A
    credential id longer than WebAuthn allows is refused, and one already registered
    raises :class:`DuplicateRecordError` when it is saved.

    Args:
        user: The signed-in account adding the passkey.
        rp: The relying party.
        credential: The ``RegistrationResponseJSON`` that ``startRegistration`` returned.
        nickname: The passkey's name, or ``None``.

    Returns:
        The saved passkey.

    Raises:
        PasskeyError: If no challenge for this account is waiting or it expired, or if the
            answer does not verify.
    """
    challenge = _take_challenge(REGISTER_CHALLENGE_KEY, user_id=user.id)
    if challenge is None:
        raise PasskeyError(EXPIRED)
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
    id_length = len(verified.credential_id)
    if id_length > MAX_CREDENTIAL_ID_BYTES:
        _log.warning('A passkey registration was refused: a %d-byte id', id_length)
        raise PasskeyError(NOT_VERIFIED)
    return _save_new_passkey(user, _new_passkey(verified, parsed, nickname))


def authentication_options(rp: RelyingParty) -> str:
    """Build sign-in options for any of the site's passkeys, and keep their challenge.

    They name no credentials, so the browser offers every passkey it holds for the RP ID,
    in its own prompt or in the email field's autofill.

    Args:
        rp: The relying party.

    Returns:
        The options as JSON, for ``startAuthentication``.
    """
    options = generate_authentication_options(
        rp_id=rp.id,
        timeout=CHALLENGE_TTL_SECONDS * 1000,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _store_challenge(LOGIN_CHALLENGE_KEY, options.challenge, user_id=None)
    return options_to_json(options)


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


def verify_authentication(rp: RelyingParty, credential: dict[str, Any]) -> User | None:
    """Check a sign-in answer, then record the passkey's use.

    Every refusal looks the same to the caller, so an answer learns nothing about which
    passkeys exist. The authenticator must have verified its user, and a counter that
    does not move past the saved one is refused unless both are 0, which synced passkeys
    always report.

    Args:
        rp: The relying party.
        credential: The ``AuthenticationResponseJSON`` that ``startAuthentication``
            returned.

    Returns:
        The passkey's account, or ``None`` when no challenge is waiting or it expired, no
        saved passkey matches, or the answer does not verify.
    """
    challenge = _take_challenge(LOGIN_CHALLENGE_KEY, user_id=None)
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

    :func:`~src_back.services.auth.require_another_sign_in_method` refuses the last one.

    Args:
        user: The signed-in account.
        passkey_id: The passkey's id.

    Returns:
        ``True`` once the passkey is gone, ``False`` if the account has none with that id.
    """
    passkey = _owned_passkey(user, passkey_id)
    if passkey is None:
        return False
    require_another_sign_in_method(user)
    PASSKEY_AUDIT_TRAIL.log_deleted(passkey)
    user.passkeys.remove(passkey)
    db.session.commit()
    return True
```

### `src_back/api/passkeys.py` — new

```python
"""Passkeys: the two WebAuthn ceremonies and the signed-in account's passkeys.

The options routes are GETs: host nginx's sign-in throttle counts POSTs, and the sign-in
page asks for options on every visit, for its autofill. Each writes a challenge into the
session, so its answer carries ``Cache-Control: no-store``. Without
``PUBLIC_BASE_URL`` the four ceremony routes answer 404, while listing, renaming, and
deleting still work. ``ai/auth.md`` walks through the flow.
"""

from flask import Blueprint, Response, jsonify
from flask_login import login_required

from src_back.auth import current_user
from src_back.schemas.passkeys import (
    passkey_assertion_schema,
    passkey_register_schema,
    passkey_rename_schema,
    passkey_schema,
)
from src_back.schemas.user import user_schema
from src_back.services.auth import complete_login
from src_back.services.errors import (
    DuplicateRecordError,
    InactiveAccountError,
    LastSignInMethodError,
    PasskeyError,
)
from src_back.services.passkeys import (
    authentication_options,
    delete_passkey,
    list_passkeys,
    registration_options,
    rename_passkey,
    rp_settings,
    verify_authentication,
    verify_registration,
)
from src_back.utils import (
    ErrorResponse,
    bad_request,
    conflict,
    dump_or_404,
    forbidden,
    not_found,
    parse_request_json,
    unauthorized,
)

bp = Blueprint('passkeys', __name__)

DISABLED = 'Passkeys are not enabled.'
NOT_ACCEPTED = 'That passkey was not accepted.'


def _options_response(options_json: str) -> Response:
    """Answer with a ceremony's options, which no cache may keep.

    Args:
        options_json: The options as py_webauthn serialized them.

    Returns:
        The JSON response.
    """
    response = Response(options_json, mimetype='application/json')
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.get('/register/options')
@login_required
def register_options() -> Response | ErrorResponse:
    """Start adding a passkey to the signed-in account.

    Returns:
        The registration options, or a 404 envelope when passkeys are off.
    """
    rp = rp_settings()
    if rp is None:
        return not_found(DISABLED)
    return _options_response(registration_options(current_user, rp))


@bp.post('/register/verify')
@login_required
def register_verify() -> tuple[Response, int]:
    """Finish adding a passkey with the browser's answer.

    A payload that fails validation never reaches this body: ``parse_request_json``
    raises and the application answers with a 422 envelope.

    Returns:
        The saved passkey with status 201; a 404 envelope when passkeys are off, a 400
        envelope when the request expired or the answer does not verify, or a 409
        envelope when the passkey is already registered.
    """
    rp = rp_settings()
    if rp is None:
        return not_found(DISABLED)
    data = parse_request_json(passkey_register_schema)
    try:
        passkey = verify_registration(
            current_user, rp, data['credential'], data['nickname']
        )
    except PasskeyError as exc:
        return bad_request(str(exc))
    except DuplicateRecordError as exc:
        return conflict(str(exc))
    return jsonify(passkey_schema.dump(passkey)), 201


@bp.get('/login/options')
def login_options() -> Response | ErrorResponse:
    """Start a sign-in with any of the site's passkeys; open to anyone.

    Returns:
        The sign-in options, or a 404 envelope when passkeys are off.
    """
    rp = rp_settings()
    if rp is None:
        return not_found(DISABLED)
    return _options_response(authentication_options(rp))


@bp.post('/login/verify')
def login_verify() -> Response | ErrorResponse:
    """Sign in with the passkey the browser chose, ending as password login does.

    Returns:
        The serialized user; a 404 envelope when passkeys are off; the same 401 envelope
        for every refusal; or a 403 envelope for a deactivated account, which only an
        answer that verified reaches.
    """
    rp = rp_settings()
    if rp is None:
        return not_found(DISABLED)
    data = parse_request_json(passkey_assertion_schema)
    user = verify_authentication(rp, data['credential'])
    if user is None:
        return unauthorized(NOT_ACCEPTED)
    try:
        complete_login(user)
    except InactiveAccountError as exc:
        return forbidden(str(exc))
    return jsonify(user_schema.dump(user))


@bp.get('')
@login_required
def list_account_passkeys() -> Response:
    """List the signed-in account's passkeys.

    Returns:
        Its passkeys, oldest first, without their key material.
    """
    return jsonify(passkey_schema.dump(list_passkeys(current_user), many=True))


@bp.put('/<int:passkey_id>')
@login_required
def rename_account_passkey(passkey_id: int) -> tuple[Response, int]:
    """Rename one of the signed-in account's passkeys.

    Args:
        passkey_id: The passkey's id.

    Returns:
        The renamed passkey, or a 404 envelope when the account has no such passkey.
    """
    data = parse_request_json(passkey_rename_schema)
    passkey = rename_passkey(current_user, passkey_id, data['nickname'])
    return dump_or_404(passkey, passkey_schema)


@bp.delete('/<int:passkey_id>')
@login_required
def delete_account_passkey(passkey_id: int) -> tuple[str, int] | ErrorResponse:
    """Delete one of the signed-in account's passkeys.

    Args:
        passkey_id: The passkey's id.

    Returns:
        An empty 204, a 404 envelope when the account has no such passkey, or a 409
        envelope when it is the account's last way to sign in.
    """
    try:
        removed = delete_passkey(current_user, passkey_id)
    except LastSignInMethodError as exc:
        return conflict(str(exc))
    if not removed:
        return not_found()
    return '', 204
```

### `src_back/api/__init__.py` and `src_back/app.py` — registration

In `api/__init__.py`, add `from src_back.api.passkeys import bp as passkeys_bp` after the
`oauth` import and `'passkeys_bp'` to `__all__` after `'oauth_bp'`. In
`_register_blueprints` in `app.py`, the import becomes one name per line, since the sixth
name takes it past 90 characters, and the blueprint registers after `oauth_bp`:

```python
    from src_back.api import (
        audit_logs_bp,
        auth_bp,
        health_bp,
        oauth_bp,
        passkeys_bp,
        users_bp,
    )

    app.register_blueprint(health_bp, url_prefix='/api')
    app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')
    app.register_blueprint(oauth_bp, url_prefix='/api/v1/auth/oauth')
    app.register_blueprint(passkeys_bp, url_prefix='/api/v1/auth/passkeys')
    app.register_blueprint(users_bp, url_prefix='/api/v1/users')
    app.register_blueprint(audit_logs_bp, url_prefix='/api/v1/audit-logs')
```

### `src_back/tests/software_authenticator.py` — new

A passkey in software, so both `verify_*` calls run for real. Its CBOR goes through
py_webauthn's `encode_cbor`, so the key map survives py_webauthn's decode and re-encode
byte for byte, and the tests import no `cbor2` of their own. It cannot import
`conftest.py`, which imports it, so it keeps its own copy of the test origin.

```python
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
```

### `src_back/tests/conftest.py` — two fixtures

Import `SoftwareAuthenticator` from `src_back.tests.software_authenticator` after the
`helpers` import, and add after `linked_user`:

```python
@pytest.fixture()
def authenticator() -> SoftwareAuthenticator:
    return SoftwareAuthenticator()


@pytest.fixture()
def passkey_user(passwordless_user: User, authenticator: SoftwareAuthenticator) -> User:
    # A passkey is its only way in, as for an account a provider created that added a
    # passkey and then unlinked the provider.
    persist(authenticator.credential_for(passwordless_user))
    return passwordless_user
```

### `src_back/tests/test_passkeys.py` — new, the service

Every service call reads the session or the config, so the tests run inside a request.
These helpers open the file:

```python
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
```

A test that inspects the database after a commit rolls the session back first, as #29's
tests do, so it sees only what was committed. Tests, with what each asserts:

- `test_rp_settings_derive_from_the_public_base_url`: id `app.test`, origin
  `https://app.test`, and the name is `app.config['WEBAUTHN_RP_NAME']`, which a
  developer's `APP_NAME` may set.
- `test_rp_settings_rebuild_the_origin_a_browser_reports`, parametrized over
  `PUBLIC_BASE_URL` set in `app.config` inside a fresh request context:
  `https://Example.COM` gives `example.com` and `https://example.com`;
  `https://example.com:443` gives `https://example.com`; `http://localhost:80` gives
  `http://localhost`; `http://localhost:5174` and `https://example.com:8443` keep their
  ports.
- `test_rp_settings_are_off_without_a_host`, parametrized over `None` and
  `localhost:5174`, which `urlsplit` reads as a scheme with no host: `None`.
- `test_rp_settings_are_off_for_a_url_that_does_not_parse` (`caplog`), parametrized over
  `http://localhost:abc`, whose `parts.port` raises, and `http://[::1:5174`, which
  `urlsplit` itself refuses: `None` and the warning, where either `ValueError` would
  reach every route as a 500.
- `test_registration_options_ask_for_a_discoverable_passkey`: the JSON's `rp` is
  `{'id': 'app.test', 'name': rp.name}`; `user` has the id
  `bytes_to_base64url(user.uuid.encode())` and the email as `name` and `displayName`;
  `authenticatorSelection` has `residentKey` `required`, `requireResidentKey` `True`, and
  `userVerification` `required`; `timeout` is 300000; `attestation` is `none`;
  `excludeCredentials` is `[]`. `session[REGISTER_CHALLENGE_KEY]` holds that challenge and
  the user's id.
- `test_registration_options_exclude_the_accounts_passkeys` (`passkey_user`,
  `authenticator`): `excludeCredentials` is
  `[{'id': bytes_to_base64url(authenticator.credential_id), 'type': 'public-key',
  'transports': ['internal', 'hybrid']}]`.
- `test_registration_options_skip_a_transport_py_webauthn_no_longer_knows`: a passkey
  saved with `transports='internal,teleport'` is excluded with `['internal']` alone.
- `test_verify_registration_saves_every_field`: called with the nickname `Laptop`, then
  rolled back and reloaded: `credential_id`, `public_key` equal to
  `authenticator.cose_public_key()`, `sign_count` 0, `transports` `internal,hybrid`,
  `aaguid` `00000000-0000-0000-0000-000000000000`, both backup flags `False`, `nickname`,
  and `user_id`.
- `test_verify_registration_records_backup_eligibility_and_state`, parametrized:
  `SoftwareAuthenticator(synced=True)` gives both `True`, and the flags
  `USER_PRESENT | USER_VERIFIED | ATTESTED_CREDENTIAL | BACKUP_ELIGIBLE` give eligible
  `True` and backed up `False`, which tells the two fields apart. The expected booleans
  come after `*` in the signature, as `test_oauth_providers.py:103` does for Ruff's
  `FBT001`.
- `test_verify_registration_keeps_the_aaguid`: an authenticator built with the bytes of
  the UUID `ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4` saves that string.
- `test_verify_registration_requires_user_verification`:
  `flags=USER_PRESENT | ATTESTED_CREDENTIAL`, as a security key without a PIN answers,
  raises `PasskeyError` with `NOT_VERIFIED` and saves nothing.
- `test_verify_registration_keeps_known_transports_once`: `['usb', 'usb', 'teleport',
  'nfc']` saves `usb,nfc`, and `[]` saves `None`.
- `test_verify_registration_needs_a_waiting_challenge`: verifying without options raises
  `PasskeyError` with `EXPIRED`.
- `test_verify_registration_refuses_an_expired_challenge`: after
  `session[REGISTER_CHALLENGE_KEY]['issued_at'] -= CHALLENGE_TTL_SECONDS + 1`, `EXPIRED`.
- `test_verify_registration_refuses_another_accounts_challenge`: options built for
  `admin_user`, answered as `user`: `EXPIRED`, and nothing saved.
- `test_verify_registration_spends_the_challenge`: the same answer twice; the second
  raises `EXPIRED`.
- `test_verify_registration_refuses_an_answer_that_does_not_verify`, parametrized, each
  raising `PasskeyError` with `NOT_VERIFIED` and saving nothing: another origin
  (`origin='https://evil.test'`); another RP ID (the options' `rp.id` changed to
  `evil.test` before `create`); no user presence
  (`flags=USER_VERIFIED | ATTESTED_CREDENTIAL`); backed up without eligibility
  (`flags=USER_PRESENT | USER_VERIFIED | ATTESTED_CREDENTIAL | BACKED_UP`); `{}`; and
  `{'id': 1}`.
- `test_verify_registration_refuses_a_key_without_its_fields`: with
  `monkeypatch.setattr(authenticator, 'cose_public_key', lambda: encode_cbor({1: 2,
  3: -7}))`, py_webauthn's `KeyError` becomes `NOT_VERIFIED`.
- `test_verify_registration_refuses_a_key_that_is_not_a_map`: the same with
  `encode_cbor([0, 2])`, which py_webauthn indexes into an `IndexError`, outside any
  exception list it documents.
- `test_verify_registration_refuses_a_point_off_the_curve`: the same with x and y both
  `(1).to_bytes(32, 'big')`; py_webauthn accepts it, and the service's own key build
  refuses it with `NOT_VERIFIED`.
- `test_verify_registration_caps_the_credential_id`:
  `credential_id=secrets.token_bytes(1024)` raises `NOT_VERIFIED` and saves nothing;
  `credential_id=secrets.token_bytes(1023)` saves, which step 4 of Verification runs
  against PostgreSQL's unique index. The bytes are random because PostgreSQL compresses an
  index value over about 510 bytes, so all zeros would index a few compressed bytes.
- `test_verify_registration_logs_why_it_refused` (`caplog`): the warning names the
  refusal.
- `test_verify_registration_refuses_a_registered_credential`: the same authenticator
  registered twice, through fresh options, raises `DuplicateRecordError` with
  `ALREADY_REGISTERED`; one row remains.
- `test_verify_registration_is_audited`: one `webauthn_credentials` entry, `created`, its
  `record_label` the nickname, its changes `user_id`, `nickname`, and `aaguid`, and
  `audited_tables()['webauthn_credentials']` is `True`.
- `test_authentication_options_name_no_credentials`: `rpId` `app.test`,
  `allowCredentials` `[]`, `userVerification` `required`, `timeout` 300000, and
  `session[LOGIN_CHALLENGE_KEY]` holds the challenge with no account.
- `test_verify_authentication_records_the_use` (`passkey_user`): it returns the account;
  after a rollback the passkey's `sign_count` is 1, `backup_state` `False`, and
  `last_used_at` within a minute of now. SQLite reads it back without an offset, so the
  test gives a naive value `tzinfo=UTC` before comparing.
- `test_verify_authentication_follows_the_backup_state`: a synced authenticator's passkey,
  saved with `backup_state=False`, reads `True` after signing in.
- `test_verify_authentication_requires_user_verification`: `flags=USER_PRESENT` returns
  `None`.
- `test_verify_authentication_accepts_a_counter_that_stays_at_zero`:
  `counter_step=0` with a saved 0 signs in, as synced passkeys do.
- `test_verify_authentication_refuses_a_counter_that_does_not_advance`:
  `sign_count=5, counter_step=0` returns `None`, and the counter stays 5.
- `test_verify_authentication_stores_the_largest_counter`: `sign_count=2**32 - 2`
  signs in and stores 4,294,967,295, which PostgreSQL's `integer` would refuse.
- `test_verify_authentication_refuses_an_unknown_passkey`: an authenticator that was
  never saved returns `None`.
- `test_verify_authentication_refuses_another_user_handle`, parametrized over
  `bytes_to_base64url(b'someone-else')`, `None`, and `'A'`, which is not base64url and
  raises `binascii.Error` inside py_webauthn: each returns `None`, never raises.
- `test_verify_authentication_refuses_an_answer_that_does_not_verify`, parametrized:
  another origin, a signature over other data (the answer's `signature` replaced by
  another key's), no user presence (`flags=USER_VERIFIED`), `{}`, and `{'id': 'x',
  'rawId': 'x', 'type': 'public-key', 'response': {}}`.
- `test_verify_authentication_refuses_a_saved_key_cryptography_refuses`: a row persisted
  with the off-curve key returns `None` instead of raising cryptography's `ValueError`.
- `test_verify_authentication_needs_a_fresh_challenge`: no options, an expired challenge,
  and a replayed answer each return `None`. The replay comes from
  `SoftwareAuthenticator(counter_step=0)`, whose counter cannot refuse it, so only the
  spent challenge can.
- `test_list_passkeys_oldest_first`.
- `test_webauthn_credential_repr`: `<WebAuthnCredential {id} user={user_id}>`, which
  coverage needs, as `test_schemas.py:173` covers `User.__repr__`.
- `test_rename_passkey_changes_the_nickname_and_is_audited`: an `updated` entry with
  `{'nickname': {'old': None, 'new': 'Phone'}}`.
- `test_rename_passkey_to_the_same_name_logs_nothing`.
- `test_rename_passkey_ignores_another_accounts_passkey`: `None`, unchanged.
- `test_delete_passkey_removes_it_and_is_audited` (a password account): `True`, the row
  gone after a rollback, and a `deleted` entry.
- `test_delete_passkey_ignores_another_accounts_passkey`: `False`, row kept.
- `test_delete_passkey_refuses_the_last_way_to_sign_in` (`passkey_user`):
  `LastSignInMethodError` with `LAST_METHOD`; the row and no entry remain.

### `src_back/tests/test_passkeys_api.py` — new, the routes

Helpers `register(client, authenticator, nickname=None)` and
`sign_in_with(client, authenticator)` run each ceremony's GET and POST through the client,
and `me_from_the_session_cookie` drops `g._login_user` before `/me`, as
`test_oauth_api.py:136-140` does. Tests:

- `test_register_options_need_a_session`: 401.
- `test_options_are_json_no_cache_keeps`, for both options routes: 200,
  `application/json`, `Cache-Control: no-store`, and a `challenge`.
- `test_register_verify_answers_201_with_the_passkey` (`auth_client`): the body has `id`,
  `uuid`, `nickname`, `transports`, `aaguid`, both backup flags, `last_used_at`, and the
  timestamps, and none of `credential_id`, `public_key`, `sign_count`, or `user_id`; the
  audit entry's `changed_by_id` is the user.
- `test_register_verify_trims_the_nickname`: `'  Laptop  '` saves `Laptop`, and `'   '`
  saves `None`.
- `test_register_verify_answers_400_for_an_expired_request` and
  `..._for_an_answer_that_does_not_verify`: the messages `EXPIRED` and `NOT_VERIFIED`.
- `test_register_verify_answers_409_for_a_registered_passkey`.
- `test_register_verify_validates_the_body`, parametrized over `{}`,
  `{'credential': None}`, `{'credential': 'text'}`, `{'credential': {}, 'nickname':
  'x' * 65}`, and `{'credential': {}, 'role': 'admin'}`: 422.
- `test_register_verify_needs_a_session`: 401.
- `test_ceremonies_answer_404_without_a_public_base_url`: with
  `app.config['PUBLIC_BASE_URL'] = None`, both options routes and both verify routes
  answer 404 `Passkeys are not enabled.`, and the list still answers 200.
- `test_login_options_are_open_to_anyone`: 200 for an anonymous client.
- `test_login_verify_signs_in` (`passkey_user`): 200 with the account's payload; `/me`
  from the session cookie answers 200 for it; the session cookie carries `Expires`, as
  `complete_login` makes it permanent.
- `test_a_registered_passkey_signs_in` (`auth_client`): register, log out, then
  `sign_in_with` answers 200, and the list shows a `last_used_at`.
- `test_login_verify_answers_401_alike`, parametrized over an unknown passkey and another
  account's user handle: 401 `That passkey was not accepted.`, and `/me` from the session
  cookie answers 401.
- `test_a_spent_answer_is_refused`: with `SoftwareAuthenticator(counter_step=0)`, the
  same answer posted twice from one client answers 200, then 401.
- `test_login_verify_answers_403_for_a_deactivated_account`: a passkey on
  `inactive_user` answers 403 `Account is inactive.`, and `/me` answers 401.
- `test_login_verify_validates_the_body`: `{}` and `{'credential': []}` answer 422.
- `test_list_needs_a_session` and `test_list_shows_only_the_callers_passkeys`.
- `test_rename_answers_200_with_the_new_nickname`, and `{'nickname': None}` clears it.
- `test_rename_of_another_accounts_passkey_is_404`.
- `test_rename_validates_the_body`: `{}` and a 65-character nickname answer 422.
- `test_delete_answers_204` (a password account).
- `test_delete_of_another_accounts_passkey_is_404`.
- `test_delete_of_the_last_way_to_sign_in_is_409` (`passkey_user`, signed in with its
  passkey): 409 `LAST_METHOD`, and the list still holds it.
- `test_delete_needs_a_session`: 401.

### `src_back/tests/test_auth.py`, `test_oauth_api.py`, `test_schemas.py` — additions

- `test_auth.py`: `test_count_sign_in_methods_counts_each_passkey`: `linked_user`
  counts 1; with the fixture authenticator's passkey persisted, 2; with a second
  `SoftwareAuthenticator()`'s, 3.
- `test_oauth_api.py`: `test_unlink_is_allowed_while_a_passkey_remains`: `linked_user`
  with a persisted passkey signs in through Google (`sign_in`), and unlinking Google
  answers 204.
- `test_schemas.py`:
    - `test_passkey_schema_hides_the_key_material` (`passkey_user`): the dump has
      `nickname` and `last_used_at` and none of `credential_id`, `public_key`,
      `sign_count`, or `user_id`.
    - `test_passkey_nickname_is_trimmed_before_its_length_rule`, for both nickname
      schemas: `'  Laptop  '` loads `Laptop`, `'   '` loads `None`, 64 characters padded
      with spaces load, and 65 fail.
    - `test_passkey_register_schema_defaults_the_nickname_to_none`.
    - `test_passkey_rename_schema_requires_the_nickname_key`: `{}` fails, and
      `{'nickname': None}` loads `None`.
    - `test_passkey_nickname_hook_passes_other_payloads_to_validation`: a list payload
      and `{'nickname': 5}` raise `ValidationError`, not `AttributeError`.
    - `test_passkey_assertion_schema_requires_a_credential_object`: `{}` and
      `{'credential': 'x'}` fail, and `{'credential': {}}` loads.

### `package.json` and `package-lock.json` — the browser library

`npm install @simplewebauthn/browser@^14.0.0`, which adds `"@simplewebauthn/browser":
"^14.0.0"` to `dependencies`. `vite.config.ts` is unchanged: only the lazy Login and
Account chunks import it.

### `src_front/src/types/auth.ts` — `Passkey` and `PasskeyPayload`

After `LinkedAccount`:

```ts
/** A passkey that can sign in to the signed-in account. */
export interface Passkey {
    id: number
    uuid: string
    /** The name the account gave it, or null for none. */
    nickname: string | null
    /** The authenticator model's id; all zeros when it keeps that private. */
    aaguid: string | null
    /** The browser's comma-joined transport hints, such as `internal,hybrid`. */
    transports: string | null
    /** Whether the passkey can sync to the person's other devices. */
    backup_eligible: boolean
    /** Whether it has synced. */
    backup_state: boolean
    /** When it last answered a sign-in, or null if it never has. */
    last_used_at: string | null
    created_at: string
    updated_at: string
}

/** The body that names a passkey, when adding or renaming it. */
export interface PasskeyPayload {
    nickname: string | null
}
```

### `src_front/src/api/client.ts` — the passkey routes' 401

The comment on `UnauthorizedHandler` (line 25) becomes "Callback run when a request
outside the sign-in steps is refused with 401." Replace `reportLostSession` (lines 90-108)
with these:

```ts
/** Under `/v1/auth/`, the routes of a signed-in account, whose 401 is a lost session. */
const SIGNED_IN_AUTH_PATHS = ['/v1/auth/oauth', '/v1/auth/passkeys']

/** The passkey sign-in, whose 401 is a refused passkey, as a wrong password is. */
const PASSKEY_SIGN_IN_PATH = '/v1/auth/passkeys/login'

/**
 * Tell whether a URL is a path or lies beneath it.
 *
 * @param url - The request URL, relative to the API base.
 * @param path - The path to compare with.
 * @returns True for the path itself and anything under it.
 */
function isUnder(url: string, path: string): boolean {
    return url === path || url.startsWith(`${path}/`)
}

/**
 * Tell whether a 401 from a URL means a sign-in failed rather than a session was lost.
 *
 * Every `/v1/auth/` route is a sign-in step but the linked accounts and the passkeys,
 * which serve a signed-in account, and of those only the passkey sign-in is a step again.
 * The passkey list is `/v1/auth/passkeys` itself, with no trailing slash.
 *
 * @param url - The request URL, relative to the API base.
 * @returns True when the 401 is a form error, such as a wrong password.
 */
function isSignInStep(url: string | undefined): boolean {
    if (!url?.startsWith('/v1/auth/')) return false
    if (isUnder(url, PASSKEY_SIGN_IN_PATH)) return true
    return !SIGNED_IN_AUTH_PATHS.some((path) => isUnder(url, path))
}

/**
 * Run the registered handler when a request was refused for want of a session.
 *
 * A 401 from a sign-in step is skipped: a wrong password or a refused passkey is a form
 * error, not a lost session. The linked accounts under `/v1/auth/oauth/` and the passkeys
 * under `/v1/auth/passkeys` are ordinary signed-in requests, so their 401 counts.
 *
 * @param error - The rejection axios produced for a failed request.
 * @returns A promise rejected with the same error.
 */
function reportLostSession(error: AxiosError): Promise<never> {
    if (error.response?.status === 401 && !isSignInStep(error.config?.url)) {
        unauthorizedHandler?.()
    }
    return Promise.reject(error)
}
```

### `src_front/src/utils/passkeys.ts` — new

```ts
/** @file Telling a cancelled passkey prompt from a failure, and describing a passkey. */

import { WebAuthnError } from '@simplewebauthn/browser'

import type { Passkey } from '../types/auth'
import { formatLocalDateTime } from './dates'

/**
 * Tell whether a passkey prompt ended because the visitor dismissed it, it timed out, or
 * a newer ceremony replaced it.
 *
 * The browser reports a dismissal and a timeout alike, as `NotAllowedError`, so neither
 * is shown as a failure.
 *
 * @param err - What the ceremony rejected with.
 * @returns True for a cancellation.
 */
export function isCancelledCeremony(err: unknown): boolean {
    return (
        err instanceof WebAuthnError &&
        (err.code === 'ERROR_CEREMONY_ABORTED' || err.name === 'NotAllowedError')
    )
}

/**
 * Explain why the browser created no passkey.
 *
 * @param err - What `startRegistration` rejected with.
 * @returns The error to show in the dialog.
 */
export function registrationFailure(err: unknown): Error {
    if (isCancelledCeremony(err)) return new Error('Passkey setup was cancelled.')
    if (
        err instanceof WebAuthnError &&
        err.code === 'ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED'
    ) {
        return new Error('This device already holds a passkey for your account.')
    }
    return err instanceof Error ? err : new Error('Passkey setup failed.')
}

/**
 * Name a passkey in its list.
 *
 * @param passkey - The passkey.
 * @returns Its nickname, or a stand-in without one.
 */
export function passkeyName(passkey: Passkey): string {
    return passkey.nickname ?? 'Unnamed passkey'
}

/**
 * Say when a passkey was added and last signed in.
 *
 * @param passkey - The passkey.
 * @returns For example `Added Oct 9, 2026, 5:00 PM, never used`.
 */
export function describePasskeyUse(passkey: Passkey): string {
    const added = `Added ${formatLocalDateTime(passkey.created_at)}`
    const used = passkey.last_used_at
        ? `last used ${formatLocalDateTime(passkey.last_used_at)}`
        : 'never used'
    return `${added}, ${used}`
}
```

### `src_front/src/api/passkeys.ts` — new

It exports what other modules use: `passkeysApi`, in the `ResourceApi` shape that
`useResourceMutations` drives, and the two sign-in calls. `create` is the registration
ceremony, so an Add in a `RecordSection` runs the browser's prompt between its two
requests. A browser call in an API module has a precedent in `api/downloads.ts`.

```ts
/** @file Passkeys: the ceremonies' endpoints, and the signed-in account's passkeys. */

import {
    startRegistration,
    type AuthenticationResponseJSON,
    type PublicKeyCredentialCreationOptionsJSON,
    type PublicKeyCredentialRequestOptionsJSON,
    type RegistrationResponseJSON,
} from '@simplewebauthn/browser'

import type { AuthUser, Passkey, PasskeyPayload } from '../types/auth'
import { registrationFailure } from '../utils/passkeys'
import client from './client'
import type { ResourceApi } from './resources'

/** Where the passkey endpoints live, relative to the API base. */
const PASSKEYS_URL = '/v1/auth/passkeys'

/**
 * Fetch the options that let the browser create a passkey for the signed-in account.
 *
 * @returns The options; the server keeps their challenge for five minutes.
 */
async function registerOptions(): Promise<PublicKeyCredentialCreationOptionsJSON> {
    const { data } = await client.get<PublicKeyCredentialCreationOptionsJSON>(
        `${PASSKEYS_URL}/register/options`,
    )
    return data
}

/**
 * Save the passkey the browser created.
 *
 * @param credential - The browser's answer to the registration options.
 * @param nickname - The passkey's name, or null for none.
 * @returns The saved passkey.
 */
async function registerVerify(
    credential: RegistrationResponseJSON,
    nickname: string | null,
): Promise<Passkey> {
    const { data } = await client.post<Passkey>(`${PASSKEYS_URL}/register/verify`, {
        credential,
        nickname,
    })
    return data
}

/**
 * Add a passkey: fetch the options, let the browser create it, then save it.
 *
 * @param payload - The passkey's nickname.
 * @returns The saved passkey. A prompt that created nothing rejects with a message that
 *   says why, such as a dismissal.
 */
async function addPasskey(payload: PasskeyPayload): Promise<Passkey> {
    const optionsJSON = await registerOptions()
    let credential: RegistrationResponseJSON
    try {
        credential = await startRegistration({ optionsJSON })
    } catch (err: unknown) {
        throw registrationFailure(err)
    }
    return registerVerify(credential, payload.nickname)
}

/**
 * Fetch the signed-in account's passkeys.
 *
 * @returns The passkeys, oldest first.
 */
async function listPasskeys(): Promise<Passkey[]> {
    const { data } = await client.get<Passkey[]>(PASSKEYS_URL)
    return data
}

/**
 * Rename one of the signed-in account's passkeys.
 *
 * @param id - The passkey's id.
 * @param payload - The new nickname, or null to clear it.
 * @returns The renamed passkey.
 */
async function renamePasskey(id: number, payload: PasskeyPayload): Promise<Passkey> {
    const { data } = await client.put<Passkey>(`${PASSKEYS_URL}/${id}`, payload)
    return data
}

/**
 * Delete one of the signed-in account's passkeys.
 *
 * @param id - The passkey's id.
 * @returns A promise that settles when the passkey is gone; it rejects with the server's
 *   message when the passkey is the account's last way to sign in.
 */
async function deletePasskey(id: number): Promise<void> {
    await client.delete(`${PASSKEYS_URL}/${id}`)
}

/** The signed-in account's passkeys, in the shape `useResourceMutations` drives. */
export const passkeysApi: ResourceApi<Passkey, PasskeyPayload> = {
    list: listPasskeys,
    create: addPasskey,
    update: renamePasskey,
    remove: deletePasskey,
}

/**
 * Fetch the options that let the browser sign in with any of the site's passkeys.
 *
 * @returns The options, which name no credentials.
 */
export async function loginOptions(): Promise<PublicKeyCredentialRequestOptionsJSON> {
    const { data } = await client.get<PublicKeyCredentialRequestOptionsJSON>(
        `${PASSKEYS_URL}/login/options`,
    )
    return data
}

/**
 * Sign in with the passkey the browser chose.
 *
 * @param credential - The browser's answer to the sign-in options.
 * @returns The response wrapping the signed-in user, as `login` returns it.
 */
export const loginVerify = (credential: AuthenticationResponseJSON) =>
    client.post<AuthUser>(`${PASSKEYS_URL}/login/verify`, { credential })
```

### `src_front/src/schemas/passkey.ts` — new

```ts
/** @file Validation and payload mapping for the passkey nickname form. */

import { z } from 'zod'

import type { Passkey, PasskeyPayload } from '../types/auth'

/** The longest nickname the server accepts. */
const NICKNAME_MAX_LENGTH = 64

/** The nickname form, whose one field may be left blank. */
export const passkeyFormSchema = z.object({
    nickname: z
        .string()
        .trim()
        .max(NICKNAME_MAX_LENGTH, `Use ${NICKNAME_MAX_LENGTH} characters or fewer.`),
})

/** The nickname form's values. */
type PasskeyFormValues = z.infer<typeof passkeyFormSchema>

/**
 * Build the form's starting values from the passkey being renamed, or a blank.
 *
 * @param passkey - The passkey being renamed, or null when adding one.
 * @returns The default values.
 */
export function passkeyFormDefaults(passkey: Passkey | null): PasskeyFormValues {
    return { nickname: passkey?.nickname ?? '' }
}

/**
 * Turn validated form values into the request body; a blank nickname becomes null.
 *
 * @param values - The validated values.
 * @returns The payload.
 */
export function toPasskeyPayload(values: PasskeyFormValues): PasskeyPayload {
    return { nickname: values.nickname || null }
}
```

### `src_front/src/hooks/passkeys.ts` — new

```ts
/** @file Server state for the signed-in account's passkeys. */

import { useQuery } from '@tanstack/react-query'

import { passkeysApi } from '../api/passkeys'
import { useResourceMutations } from './resources'

/** Cache key for the signed-in account's passkeys. */
const PASSKEYS_KEY = ['passkeys'] as const

/**
 * Load the signed-in account's passkeys.
 *
 * @returns The query holding the passkeys.
 */
export const usePasskeys = () =>
    useQuery({ queryKey: PASSKEYS_KEY, queryFn: passkeysApi.list })

/**
 * Build the add, rename, and delete mutations for passkeys.
 *
 * Adding one runs the browser's prompt between its two requests.
 *
 * @returns The three mutations.
 */
export const usePasskeyMutations = () => useResourceMutations(PASSKEYS_KEY, passkeysApi)
```

### `src_front/src/hooks/useAuthFormState.ts` — a cancelled action

`handleAuthAction` takes an action that may resolve `null`, which changes nothing:

```ts
    /**
     * Run an auth request, then store the returned user and navigate.
     *
     * The register and login endpoints both answer with the signed-in user, so
     * the store is filled from that response rather than from a second `/me`
     * round trip that could fail or race the page-load reconciliation. The
     * client's interceptor has already copied any server error text into the
     * thrown `Error`; the fallback covers anything else that was thrown. An action
     * that resolves null was cancelled, as a dismissed passkey prompt is, and leaves
     * the page as it was.
     *
     * @param action - The auth call to run, such as `login` or `register`.
     * @param fallback - Message to show when the thrown value is not an `Error`.
     */
    const handleAuthAction = async (
        action: () => Promise<AxiosResponse<AuthUser> | null>,
        fallback: string,
    ) => {
        clearError()
        try {
            const response = await action()
            if (response === null) return
            setUser(response.data)
            navigate(requestedPath(location.state))
        } catch (err: unknown) {
            onErr(err instanceof Error ? err : new Error(fallback))
        }
    }
```

### `src_front/src/hooks/usePasskeyLogin.ts` — new

```ts
/** @file The sign-in page's passkeys: its button, and the email field's autofill. */

import {
    browserSupportsWebAuthn,
    browserSupportsWebAuthnAutofill,
    startAuthentication,
    WebAuthnAbortService,
    type AuthenticationResponseJSON,
    type PublicKeyCredentialRequestOptionsJSON,
} from '@simplewebauthn/browser'
import type { AxiosResponse } from 'axios'
import { useEffect, useRef, useState } from 'react'

import { loginOptions, loginVerify } from '../api/passkeys'
import type { AuthUser } from '../types/auth'
import { isCancelledCeremony } from '../utils/passkeys'

/** A sign-in that resolves null when the visitor cancelled it. */
type SignInAction = () => Promise<AxiosResponse<AuthUser> | null>

/** The sign-in page's `handleAuthAction`, which shows a failure or navigates. */
export type RunAuthAction = (action: SignInAction, fallback: string) => Promise<void>

/** What the page shows when a passkey sign-in fails without a message of its own. */
const FALLBACK_MESSAGE = 'Passkey sign-in failed.'

/** How often the autofill offer renews; the server keeps a challenge five minutes. */
const AUTOFILL_REFRESH_MS = 4 * 60 * 1000

/**
 * Sign in through the browser's own passkey prompt.
 *
 * @returns The response with the signed-in user, or null when the visitor dismissed the
 *   prompt or a newer ceremony replaced it.
 */
async function signInThroughPrompt(): Promise<AxiosResponse<AuthUser> | null> {
    const optionsJSON = await loginOptions()
    let credential: AuthenticationResponseJSON
    try {
        credential = await startAuthentication({ optionsJSON })
    } catch (err: unknown) {
        if (isCancelledCeremony(err)) return null
        throw err
    }
    return loginVerify(credential)
}

/**
 * Offer the site's passkeys in the email field's autofill, where the browser can.
 *
 * The page's `handleAuthAction` runs only once the visitor picks a passkey, because it
 * clears the page's error first, and an offer that renews must not erase the message of
 * a sign-in that just failed. Options that fail to load, and a ceremony that ends without
 * a pick, leave the page as it was.
 *
 * @param signal - Aborted when a newer offer, the button, or an unmount ends this one.
 * @param run - Runs the sign-in as `handleAuthAction` does.
 * @returns Whether the visitor picked a passkey, once its sign-in settles.
 */
async function offerAutofill(
    signal: AbortSignal,
    run: (action: SignInAction) => Promise<void>,
): Promise<boolean> {
    if (!(await browserSupportsWebAuthnAutofill()) || signal.aborted) return false
    let optionsJSON: PublicKeyCredentialRequestOptionsJSON
    try {
        optionsJSON = await loginOptions()
    } catch {
        return false
    }
    if (signal.aborted) return false
    let credential: AuthenticationResponseJSON
    try {
        credential = await startAuthentication({ optionsJSON, useBrowserAutofill: true })
    } catch {
        return false
    }
    await run(() => loginVerify(credential))
    return true
}

/**
 * Offer passkey sign-in on the sign-in page.
 *
 * The autofill offer starts when the page mounts. A browser's autofill request never
 * times out, but the server's challenge does, so the offer renews every four minutes,
 * at once after a passkey picked from it fails, and again once the button's sign-in
 * settles. The button ends the offer first, even one whose options are still loading,
 * because starting a ceremony aborts the one before it; no offer starts while the
 * button's prompt is open, and unmounting cancels whichever ceremony runs. The effects
 * read `run` through a ref, because the page's `handleAuthAction` changes on every
 * render; `eslint-plugin-react-hooks` 5 predates `useEffectEvent`.
 *
 * @param run - The page's `handleAuthAction`.
 * @returns `available`, whether this browser can use passkeys; `pending`, whether the
 *   button's sign-in is running; and `signIn`, which runs it.
 */
export function usePasskeyLogin(run: RunAuthAction) {
    const runRef = useRef(run)
    const autofillRef = useRef<AbortController | null>(null)
    const buttonBusyRef = useRef(false)
    const [offer, setOffer] = useState(0)
    const [available] = useState(browserSupportsWebAuthn)
    const [pending, setPending] = useState(false)

    useEffect(() => {
        runRef.current = run
    })

    useEffect(() => () => WebAuthnAbortService.cancelCeremony(), [])

    useEffect(() => {
        if (buttonBusyRef.current) return
        const controller = new AbortController()
        autofillRef.current = controller
        void offerAutofill(controller.signal, (action) =>
            runRef.current(action, FALLBACK_MESSAGE),
        ).then((picked) => {
            // A pick ends the browser's request, so after a failed one the offer renews.
            if (picked && !controller.signal.aborted) setOffer(offer + 1)
        })
        const timer = setTimeout(() => setOffer(offer + 1), AUTOFILL_REFRESH_MS)
        return () => {
            clearTimeout(timer)
            controller.abort()
            if (!buttonBusyRef.current) WebAuthnAbortService.cancelCeremony()
        }
    }, [offer])

    /** Sign in through the browser's prompt, which replaces the autofill offer. */
    const signIn = async () => {
        buttonBusyRef.current = true
        autofillRef.current?.abort()
        setPending(true)
        try {
            await run(signInThroughPrompt, FALLBACK_MESSAGE)
        } finally {
            buttonBusyRef.current = false
            setPending(false)
            setOffer((count) => count + 1)
        }
    }

    return { available, pending, signIn }
}
```

The review drafted this version and, in its second pass, moved the `handleAuthAction`
call after the pick; both passes checked it with Prettier, ESLint, and the TypeScript
compiler against the 14.0.0 type declarations, and the function is 48 lines. The offer
does not renew after a ceremony that ends without a pick, because some such endings need
no visitor at all, such as a `SecurityError` on `127.0.0.1`, and renewing on them would
loop GETs as fast as the server answers. The ref read in the third effect's cleanup draws
no `exhaustive-deps` warning, because `signIn` assigns `buttonBusyRef.current`, which
tells the rule the ref is not React's.

### `src_front/src/components/auth/ProviderButtons.tsx` — `ProviderLinks`

Split the links out, so `SignInOptions` renders them without a second divider:

```tsx
/** Props accepted by {@link ProviderLinks}. */
interface ProviderLinksProps {
    providers: OAuthProviderInfo[]
    next: string
}

/**
 * Render one "Continue with" link per provider.
 *
 * Each is a plain anchor, because the browser leaves the page for the provider.
 *
 * @param props - The component props.
 * @param props.providers - The enabled providers.
 * @param props.next - The path to return to after signing in.
 * @returns The links.
 */
export function ProviderLinks({ providers, next }: ProviderLinksProps) {
    return (
        <>
            {providers.map(({ name, label }) => (
                <Button
                    key={name}
                    variant="outlined"
                    fullWidth
                    href={startUrl(name, next)}
                >
                    Continue with {label}
                </Button>
            ))}
        </>
    )
}
```

`ProviderButtons` then renders `<ProviderLinks providers={providers} next={next} />` under
its divider, and its docstring drops the sentence about plain anchors, which moves to
`ProviderLinks`. Import `OAuthProviderInfo` from `../../types/auth`. Register keeps
`ProviderButtons`.

### `src_front/src/components/auth/SignInOptions.tsx` — new

```tsx
/** @file The other ways to sign in, beneath the sign-in form: a passkey and providers. */

import { Button, Divider, Stack } from '@mui/material'

import { usePasskeyLogin, type RunAuthAction } from '../../hooks/usePasskeyLogin'
import { useProviders } from '../../hooks/useProviders'
import { ProviderLinks } from './ProviderButtons'

/** Props accepted by {@link SignInOptions}. */
interface SignInOptionsProps {
    next: string
    run: RunAuthAction
}

/**
 * Render a passkey button and one link per enabled provider, behind an "or" divider.
 *
 * The button shows wherever the browser supports passkeys, and the email field's
 * autofill offers them too. With neither a passkey nor a provider to offer, it renders
 * nothing, divider included.
 *
 * @param props - The component props.
 * @param props.next - The path a provider sign-in returns to.
 * @param props.run - The page's `handleAuthAction`, which a passkey sign-in goes through.
 * @returns The options, or null.
 */
export default function SignInOptions({ next, run }: SignInOptionsProps) {
    const providers = useProviders()
    const passkey = usePasskeyLogin(run)
    if (providers.length === 0 && !passkey.available) return null
    return (
        <Stack spacing={1} sx={{ mt: 2 }}>
            <Divider>or</Divider>
            {passkey.available && (
                <Button
                    variant="outlined"
                    fullWidth
                    disabled={passkey.pending}
                    onClick={() => void passkey.signIn()}
                >
                    Sign in with a passkey
                </Button>
            )}
            <ProviderLinks providers={providers} next={next} />
        </Stack>
    )
}
```

### `src_front/src/pages/Login.tsx` — the options and the autofill hint

Three edits, which keep `Login()` at 49 lines: import `SignInOptions` from
`../components/auth/SignInOptions` in place of `ProviderButtons`; the email field's
`autoComplete="email"` becomes `autoComplete="username webauthn"` (the `webauthn` token
must come last); and `secondary` becomes:

```tsx
            secondary={<SignInOptions next={returnPath} run={handleAuthAction} />}
```

The docstring's first sentence, wrapped within 90 columns, becomes:

```tsx
/**
 * Render the sign-in form, with a passkey and the providers beneath it, and submit it
 * to the auth API.
```

### `src_front/src/components/account/Passkeys.tsx` — new

```tsx
/** @file The Account page's section for adding, renaming, and deleting passkeys. */

import { Box } from '@mui/material'
import { browserSupportsWebAuthn } from '@simplewebauthn/browser'

import { usePasskeyMutations, usePasskeys } from '../../hooks/passkeys'
import {
    passkeyFormDefaults,
    passkeyFormSchema,
    toPasskeyPayload,
} from '../../schemas/passkey'
import type { Passkey, PasskeyPayload } from '../../types/auth'
import { describePasskeyUse, passkeyName } from '../../utils/passkeys'
import FormDialog from '../common/FormDialog'
import FormTextField from '../common/FormTextField'
import QueryState from '../common/QueryState'
import RecordSection, { type RecordDialogProps } from '../common/RecordSection'

/** Why Add is off in a browser that cannot create passkeys. */
const UNSUPPORTED = 'This browser cannot create passkeys.'

/**
 * Ask for a nickname: before the browser creates a passkey, or to rename one.
 *
 * @param props - The dialog props from the owning record section.
 * @returns The dialog element.
 */
function PasskeyFormDialog(props: RecordDialogProps<Passkey, PasskeyPayload>) {
    const { open, item, onClose, onSubmit } = props
    return (
        <FormDialog
            open={open}
            title={item ? 'Rename passkey' : 'Add a passkey'}
            schema={passkeyFormSchema}
            defaultValues={passkeyFormDefaults(item)}
            submitLabel={item ? 'Save' : 'Continue'}
            onClose={onClose}
            onSubmit={(values) => onSubmit(toPasskeyPayload(values))}
        >
            <FormTextField
                name="nickname"
                label="Nickname"
                helperText="Optional: a name that tells this passkey from your others."
                autoFocus
            />
        </FormDialog>
    )
}

/**
 * Say what deleting a passkey does.
 *
 * @param passkey - The passkey about to be deleted.
 * @returns The confirmation's text.
 */
function deleteWarning(passkey: Passkey): string {
    const name = passkeyName(passkey)
    return `${name} will stop signing in here. Remove it from your device as well.`
}

/**
 * Show the signed-in account's passkeys, and let it add, rename, and delete them.
 *
 * Adding one asks for an optional nickname, then for the browser's prompt. A refused
 * delete, such as of the account's last way to sign in, shows the server's message in
 * the confirmation.
 *
 * @returns The section element.
 */
export default function Passkeys() {
    const query = usePasskeys()
    const mutations = usePasskeyMutations()
    const addDisabledReason = browserSupportsWebAuthn() ? undefined : UNSUPPORTED
    return (
        <Box component="section" sx={{ mt: 4 }}>
            <QueryState query={query}>
                {(passkeys) => (
                    <RecordSection<Passkey, PasskeyPayload>
                        title="Passkeys"
                        addLabel="Add passkey"
                        emptyText="No passkeys yet."
                        items={passkeys}
                        mutations={mutations}
                        renderPrimary={passkeyName}
                        renderSecondary={describePasskeyUse}
                        deleteTitle="Delete passkey"
                        deleteMessage={deleteWarning}
                        renderDialog={(dialog) => <PasskeyFormDialog {...dialog} />}
                        addDisabledReason={addDisabledReason}
                    />
                )}
            </QueryState>
        </Box>
    )
}
```

### `src_front/src/pages/Account.tsx` — the section

Import `Passkeys` from `../components/account/Passkeys`, render `<Passkeys />` after
`<LinkedAccounts />`, and change the docstring's first line to "Render the account page:
its sign-in providers and its passkeys."

### `src_front/src/components/common/RecordSection.tsx` — #57's first fix

In `RecordDeleteDialog`, read the id during render, as `UnlinkDialog` reads the provider:

```tsx
    // In production builds the React Compiler compares the paths confirm reads while
    // rendering, when item is still null, so the id is read safely here (#57).
    const itemId = item?.id

    /**
     * Delete the selected record, then close the confirmation, which cannot be
     * dismissed until the delete settles.
     */
    const confirm = async () => {
        // Delete is clickable only while open, and the dialog is open only with an item.
        await remove.mutateAsync(itemId!)
        onClose()
    }
```

No Vitest test can see the difference, since Vitest runs without the compiler; the
browser check in Verification opens the passkey delete confirmation in a production build.

### Frontend tests

`src_front/src/test/utils/webauthn.ts` is new, holding the stand-ins several test files
share:

```ts
/** @file WebAuthn stand-ins for the tests: options, answers, and a prompt's errors. */

import {
    WebAuthnError,
    type AuthenticationResponseJSON,
    type PublicKeyCredentialCreationOptionsJSON,
    type PublicKeyCredentialRequestOptionsJSON,
    type RegistrationResponseJSON,
} from '@simplewebauthn/browser'

/** Sign-in options as the server sends them. */
export const requestOptions: PublicKeyCredentialRequestOptionsJSON = {
    challenge: 'c2lnbi1pbi1jaGFsbGVuZ2U',
    rpId: 'localhost',
    allowCredentials: [],
    userVerification: 'required',
    timeout: 300000,
}

/** Registration options as the server sends them. */
export const creationOptions: PublicKeyCredentialCreationOptionsJSON = {
    challenge: 'cmVnaXN0ZXItY2hhbGxlbmdl',
    rp: { id: 'localhost', name: 'Flask React Template' },
    user: {
        id: 'dXNlci11dWlkLTI',
        name: 'user@example.com',
        displayName: 'user@example.com',
    },
    pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
    excludeCredentials: [],
    authenticatorSelection: { residentKey: 'required', userVerification: 'required' },
    attestation: 'none',
    timeout: 300000,
}

/** The browser's answer to the sign-in options. */
export const authenticationResponse: AuthenticationResponseJSON = {
    id: 'Y3JlZGVudGlhbC1pZA',
    rawId: 'Y3JlZGVudGlhbC1pZA',
    type: 'public-key',
    response: {
        clientDataJSON: 'e30',
        authenticatorData: 'AAAA',
        signature: 'AAAA',
        userHandle: 'dXNlci11dWlkLTI',
    },
    clientExtensionResults: {},
}

/** The browser's answer to the registration options. */
export const registrationResponse: RegistrationResponseJSON = {
    id: 'Y3JlZGVudGlhbC1pZA',
    rawId: 'Y3JlZGVudGlhbC1pZA',
    type: 'public-key',
    response: {
        clientDataJSON: 'e30',
        attestationObject: 'AAAA',
        transports: ['internal'],
    },
    clientExtensionResults: {},
}

/**
 * Build the error a passkey prompt rejects with.
 *
 * @param code - The library's code for it.
 * @param name - The browser's name for it, such as `NotAllowedError`.
 * @returns The error, as `@simplewebauthn/browser` throws it.
 */
export function ceremonyError(code: WebAuthnError['code'], name: string): WebAuthnError {
    const cause = new Error('The browser refused.')
    cause.name = name
    return new WebAuthnError({ message: cause.message, code, cause })
}
```

`fixtures.ts` gains `laptopPasskey: Passkey` (id 3, `uuid` `passkey-uuid-3`, nickname
`Laptop`, the zero AAGUID, `transports` `internal,hybrid`, both backup flags `true`,
`last_used_at` `2026-10-14T16:05:00Z`, and the shared stamps), and its `@file` line names
passkeys too.

A test that needs the real `WebAuthnError` and `WebAuthnAbortService` mocks the library in
part. Four test files do, and fallow fails a copied block of 50 tokens and 5 lines, so the
mock lives in `src_front/src/test/utils/webauthnMock.ts`, apart from `webauthn.ts`, which
imports the mocked module:

```ts
/** @file The partial mock of `@simplewebauthn/browser` that the passkey tests share. */

import { vi } from 'vitest'

/** The library's exports, as the real module provides them. */
type Browser = typeof import('@simplewebauthn/browser')

/**
 * Keep the library's errors and abort service, and replace what touches the browser.
 *
 * @param importOriginal - Vitest's loader for the real module.
 * @returns The module the tests see.
 */
export async function mockWebAuthnBrowser(
    importOriginal: () => Promise<Browser>,
): Promise<Browser> {
    return {
        ...(await importOriginal()),
        browserSupportsWebAuthn: vi.fn(),
        browserSupportsWebAuthnAutofill: vi.fn(),
        startAuthentication: vi.fn(),
        startRegistration: vi.fn(),
    }
}
```

Each such test file then opens with, adjusting the relative path to its depth:

```ts
vi.mock('@simplewebauthn/browser', async (importOriginal) =>
    (await import('../utils/webauthnMock')).mockWebAuthnBrowser(importOriginal),
)
```

Each file below, with its cases:

- `test/api/client.test.ts`: a 401 from `/v1/auth/passkeys` (the list, no trailing slash),
  `/v1/auth/passkeys/3`, and `/v1/auth/passkeys/register/options` reports a lost session;
  a 401 from `/v1/auth/passkeys/login/verify` does not; `/v1/auth/oauthx` still counts as
  a sign-in step, as before.
- `test/api/passkeys.test.ts` (client automocked, the library in part): `passkeysApi.list`
  gets `/v1/auth/passkeys`; `update` puts `/v1/auth/passkeys/3` with the payload; `remove`
  deletes `/v1/auth/passkeys/3`; `create` gets the register options, calls
  `startRegistration({ optionsJSON: creationOptions })`, posts
  `{ credential: registrationResponse, nickname: 'Phone' }` to `register/verify`, and
  resolves the saved passkey; a dismissed prompt rejects with `Passkey setup was
  cancelled.` and posts nothing; an excluded device rejects with `This device already
  holds a passkey for your account.`; `loginOptions` gets `login/options`; `loginVerify`
  posts `{ credential }` and resolves the whole response.
- `test/utils/passkeys.test.ts`: `isCancelledCeremony` is true for
  `ERROR_CEREMONY_ABORTED` and for a `NotAllowedError`, false for another code, for a
  plain `Error` named `NotAllowedError`, and for a string; `registrationFailure` maps the
  two cases above, passes another `Error` through, and wraps a non-`Error` as `Passkey
  setup failed.`; `passkeyName` with and without a nickname; `describePasskeyUse` for
  `laptopPasskey` equals `Added ${formatLocalDateTime(created_at)}, last used
  ${formatLocalDateTime(last_used_at)}`, built with `formatLocalDateTime` as
  `test/utils/dates.test.ts:49-58` builds its expectations rather than a literal that
  holds only in one locale, and ends `never used` without `last_used_at`.
- `test/schemas/passkey.test.ts`: the schema trims, refuses 65 characters with its
  message, and accepts a blank; `passkeyFormDefaults` fills from a passkey, from one
  without a nickname, and from null; `toPasskeyPayload` maps a blank to null.
- `test/hooks/passkeys.test.tsx` (`../../api/passkeys` automocked): `usePasskeys` loads
  through `passkeysApi.list`; `create`, `update`, and `remove` call the matching
  `passkeysApi` function and invalidate `['passkeys']`, as `hooks/oauth.test.tsx` checks.
- `test/hooks/usePasskeyLogin.test.tsx` (the library in part, `../../api/passkeys`
  automocked, `vi.spyOn(WebAuthnAbortService, 'cancelCeremony')`). Its `run` double awaits
  the action and records what it resolved or threw. `browserSupportsWebAuthnAutofill`
  resolves `false` unless a case says otherwise:
    - `available` follows `browserSupportsWebAuthn`.
    - With autofill, it loads the options, calls `startAuthentication` with
      `{ optionsJSON: requestOptions, useBrowserAutofill: true }`, and a pick resolves to
      `loginVerify`'s response.
    - Without autofill, it loads no options; options that fail to load run nothing.
    - An autofill ceremony that rejects, with an abort or anything else, calls no `run`,
      verifies nothing, and starts no offer before the four-minute renewal.
    - A pick whose sign-in fails renews the offer at once: the options load again.
    - After a failed button sign-in and the offer it starts, `run` has been called once,
      so the renewed offer has not cleared the page's error.
    - Unmounting calls `cancelCeremony`, also while the button's prompt is open.
      Unmounting while the support check is pending loads no options, and while the
      options load starts no ceremony.
    - `signIn` loads the options, calls `startAuthentication({ optionsJSON:
      requestOptions })` without the autofill flag, and resolves to `loginVerify`'s
      response; `pending` is true until it settles; `run` receives
      `'Passkey sign-in failed.'` as its fallback.
    - A dismissed prompt resolves to null; another ceremony error, such as
      `ERROR_INVALID_DOMAIN`, rejects with it.
    - A `run` passed in a rerender before the options load is the one the autofill uses,
      and a rerender loads the options only once.
    - With fake timers: after four minutes the options load again and a second autofill
      ceremony starts; while the button's prompt is open, the timer starts no offer and
      does not call `cancelCeremony`; once a dismissed button prompt settles, the offer
      starts again.
    - A click while the autofill's options are still loading: once they arrive,
      `startAuthentication` has been called once, without `useBrowserAutofill`, so the
      late offer cannot abort the button's prompt.
- `test/components/auth/SignInOptions.test.tsx` (`../../../hooks/usePasskeyLogin` and
  `../../../api/oauth` automocked): nothing, no separator, without a passkey or a
  provider; the divider and the button with only a passkey; the divider and the link with
  only a provider; the button before the link; a click calls `signIn`; the button is
  disabled while `pending`; `usePasskeyLogin` receives `run`.
- `test/components/auth/ProviderButtons.test.tsx`: unchanged, and passes.
- `test/pages/Login.test.tsx` (the library in part, `../../api/passkeys` automocked;
  `beforeEach` makes `browserSupportsWebAuthn` return `false` and the autofill check
  resolve `false`, so the existing cases keep their page):
    - The autofill hint test expects `username webauthn` on the email field.
    - The button signs in: the store holds the user and the page navigates home.
    - A refused passkey shows the server's message in the one alert.
    - A dismissed prompt shows no alert, stores no user, and stays on the page, which
      covers `handleAuthAction`'s null branch.
    - A pick from the autofill signs in.
    - With autofill supported and its ceremony left pending, a refused button sign-in
      keeps its alert after the renewed offer's options load.
    - With a provider, the order is Sign in, then the passkey button, then the provider.
- `test/components/account/Passkeys.test.tsx` (`../../../api/passkeys` automocked, the
  library in part, `renderWithProviders`):
    - It lists `laptopPasskey` with its name and `describePasskeyUse`, says `No passkeys
      yet.` when empty, and shows `Unnamed passkey` without a nickname.
    - Add opens `Add a passkey`; Continue with `Phone` calls `passkeysApi.create` with
      `{ nickname: 'Phone' }`, closes the dialog, and refetches; a blank nickname sends
      `{ nickname: null }`.
    - A rejected create keeps the dialog open with its message.
    - Edit opens `Rename passkey` filled with `Laptop`, and Save sends the new nickname to
      `update` with id 3.
    - Delete opens `Delete passkey` with the warning; confirming calls `remove` with 3; a
      409 keeps the confirmation open with `LAST_METHOD`'s text.
    - Without WebAuthn, Add is disabled and the reason shows.
    - A nickname of 65 characters shows the length message and sends nothing.
- `test/pages/Account.test.tsx`: mock `../../api/passkeys` with `passkeysApi.list`
  resolving `[]`, and find the level-2 heading `Passkeys` beside `Sign-in providers`.
- `test/App.test.tsx`: it renders `/account` with only the auth, health, OAuth, and users
  modules mocked (lines 16-19), so the new section would send a real request from jsdom.
  Add `vi.mock('../api/passkeys')` and, in `beforeEach`,
  `vi.mocked(passkeysApi.list).mockResolvedValue([])`; the `/account` test then finds
  `No passkeys yet.`, and the signed-out redirect test asserts `passkeysApi.list` was not
  called.
- `test/components/common/RecordSection.test.tsx`: unchanged, and passes.

### `ai/auth.md` — passkeys

In "Overview", the first paragraph's last sentence, which says Apple, Facebook, and
passkeys build on the same groundwork, becomes two: the first sentence ends "through a
sign-in provider, or with a passkey (both below).", and the second reads "Sign in with
Apple (#30) and Facebook (#31) build on the same groundwork:". The count bullet's first
sentence becomes "`count_sign_in_methods(user)` counts the ways an account can sign in: a
password, each linked provider, and each passkey."

In "Sign-in throttling", the bullet that names "the passkey ceremonies (#32)" becomes:

```markdown
- Every POST under `/api/v1/auth/` shares the budget, including a passkey's answers to
  `/passkeys/login/verify` and `/passkeys/register/verify`, and Sign in with Apple's
  callback (#30). The passkey options are GETs, so the sign-in page's autofill, which
  asks for them on every visit and every four minutes after, spends nothing. A passkey
  sign-in costs one POST, as a password sign-in does.
```

Insert this section between "Sign-in providers" and "Sign-in throttling":

````markdown
## Passkeys

A passkey is a WebAuthn credential: a key pair whose private half stays in the person's
device or password manager, and whose public half `webauthn_credentials` keeps.
`src_back/services/passkeys.py` runs the two ceremonies with `webauthn` (py_webauthn),
`src_back/api/passkeys.py` serves them under `/api/v1/auth/passkeys`, and the browser
side is `@simplewebauthn/browser`.

### Signing in with a passkey

The sign-in page offers passkeys two ways, and neither asks for an email:

- The email field's `autocomplete="username webauthn"` lets the browser list the site's
  passkeys among its suggestions. The page starts this autofill ceremony when it mounts,
  renews it every four minutes, at once after a passkey picked from it fails, and after a
  failed or dismissed button sign-in, and stops it when it unmounts. A passkey picked and
  then dismissed at the device's prompt leaves the suggestions empty until the next
  renewal; the button works meanwhile.
- "Sign in with a passkey" opens the browser's own prompt, which ends the autofill
  ceremony, because a browser runs one at a time.

Both fetch `GET /login/options`, whose options name no credentials, so the browser offers
every passkey it holds for the site, and post the browser's answer to `/login/verify`.
The server finds the passkey by its credential id, requires the answer's user handle to be
the `uuid` of that passkey's account, checks the signature and the counter, records the
counter, the backup state, and `last_used_at`, and calls `complete_login`. Every refusal
is the same 401, `That passkey was not accepted.`, and a deactivated account gets its 403
only after its passkey checked out, as with a password. A dismissed prompt changes
nothing on the page.

Both ceremonies require user verification, so a passkey is two factors: the device and
its biometric, screen lock, or PIN. A security key without a PIN must be given one first;
Chrome offers to create it, and otherwise the key maker's tool sets it.

### Managing passkeys

The Account page's Passkeys section adds, renames, and deletes the signed-in account's
passkeys. Adding one (`GET /register/options`, then `POST /register/verify`) asks for an
optional nickname, then for the browser's prompt. The options exclude the account's
passkeys, so a device that already holds one says so. A passkey counts as a sign-in
method: deleting an account's last way to sign in is a 409, and unlinking a provider is
allowed while a passkey remains. Each add, rename, and delete is audited in
`webauthn_credentials`, admin-only, because the history route serves any signed-in account
a table that is not, and would show every account's passkeys; a sign-in is not audited.

### Relying party

`rp_settings()` derives the relying party from `PUBLIC_BASE_URL`:

- The RP ID is its host name, without the scheme or port: `example.com`, or `localhost`
  in development. A passkey works only for its RP ID, so moving the site to another domain
  orphans every passkey, and staging, on its own host, can use none of production's.
- The expected origin is its scheme, host, and port, rebuilt as browsers report it, with
  the host lowercased and a default port dropped. Give the host in ASCII: browsers report
  an internationalized name in its punycode form.
- `WEBAUTHN_RP_NAME` names the site in the browser's prompt.

Without `PUBLIC_BASE_URL` the four ceremony routes answer 404 with
`Passkeys are not enabled.`, as they do, with a warning in the log, when it does not
parse, as with a port that is not a number; listing, renaming, and deleting still work.
An IP address cannot be an RP ID, so a local setup uses `localhost`, which browsers treat
as secure over plain http.

### Challenges

A ceremony's challenge waits in the Flask session for five minutes
(`CHALLENGE_TTL_SECONDS`), under `passkey_register` or `passkey_login`, and the answer
takes it out, so one answer spends it. The session works here because every passkey call
is a same-site request, which carries the `SameSite=Strict` cookie. A registration
challenge also names its account, so an answer that arrives after another account signed
in on the same browser is refused. A second sign-in tab replaces the first tab's
challenge, so a passkey picked in the first fails once. A browser's autofill request never
times out, so the sign-in page renews its offer every four minutes, before the challenge
expires.

Flask's session is a signed cookie, not a server-side store, so whoever holds both a
browser's session cookie and an answer it just sent could replay the answer until the
challenge expires. The counter stops that for authenticators that count, but synced
passkeys always report 0. Both halves leave the browser only over TLS. A server-side
record of spent challenges, such as a table a scheduled job sweeps, would close the gap;
the session costs no write per sign-in.

### Lost passkeys and compromised accounts

An account whose only way in is a passkey on a lost device cannot sign in. An admin sets
a password for it on the Users screen; its owner signs in, deletes the lost passkey on the
Account page, and adds a new one. Until it is deleted, the lost passkey still signs in for
whoever unlocks that device.

Adding a passkey asks for no fresh proof, as linking a provider does not, and a passkey
survives a password change. To clear a compromised account, follow the steps for links
in "The linking policy", reading the `webauthn_credentials` history as well, and delete
each passkey its owner does not recognize:

```sql
DELETE FROM webauthn_credentials WHERE user_id = <id> AND id = <passkey id>;
```

### Trying passkeys locally

Chrome's DevTools have a WebAuthn panel (More tools, then WebAuthn). Enable the virtual
authenticator environment, add a `ctap2` authenticator, and tick Supports resident keys
and Supports user verification, which start unticked and without which every ceremony
fails here; then add and use passkeys on `http://localhost:<port>` as on a real device.
Chrome refuses WebAuthn on a page with a certificate error, so a self-signed https origin
will not do. The backend tests use `src_back/tests/software_authenticator.py`, which
answers both ceremonies with a real P-256 key.
````

### `ai/domain.md`, `ai/project.md`, `ai/conventions.md`, `ai/staging.md`

- `ai/domain.md`:
    - The Accounts bullet ends with "A `WebAuthnCredential` is a passkey; an account has
      any number, each found at sign-in by its credential id and tied to its account by
      the user handle, the account's `uuid` (`src_back/services/passkeys.py`,
      `ai/auth.md`)."
    - In the Audit log bullet, "and each provider link in `oauth_accounts`" becomes "each
      provider link in `oauth_accounts`, and each passkey in `webauthn_credentials`".
    - Under Test Fixtures, after `linked_user`: "`authenticator` - a
      `SoftwareAuthenticator` (`src_back/tests/software_authenticator.py`), a P-256
      passkey that answers both ceremonies as a browser would" and "`passkey_user` -
      `passwordless_user` with that authenticator's passkey as its only way in".
- `ai/project.md`: the `models/` line adds "`webauthn_credential.py` holds
  `WebAuthnCredential`" after `OAuthAccount`; the `services/` line adds
  "`services/passkeys.py` the passkey ceremonies and their upkeep" before
  `services/users.py`; the `tests/` line adds "`software_authenticator.py` a software
  passkey" after `persist()`.
- `ai/conventions.md`:
    - In the exceptions bullet, "`SelfModificationError` with `bad_request(str(exc))`
      (400)" becomes "`SelfModificationError` and `PasskeyError` with
      `bad_request(str(exc))` (400)".
    - In the axios bullet, "notify the auth store on a 401" becomes "notify the auth store
      on a 401, except from a sign-in step, where a 401 is a refused credential
      (`isSignInStep` in `api/client.ts`)".
    - In the lazy-pages bullet, "add a large new dependency to one of them in
      `VENDOR_CHUNKS`" gains "; a small one that only lazy pages import, such as
      `@simplewebauthn/browser`, needs none".
- `ai/staging.md`: in "Copying production into staging", after the sentence about an
  account with no password, add "Passkeys copy too, but none works there: each is bound to
  production's host name, and staging has its own, so a tester adds a passkey on staging
  to try one. An account whose only way in is a passkey cannot sign in to staging until
  an admin there sets it a password."

### `tools.md` and `README.md`

In `tools.md`, after the `joserfc` entry under "Backend runtime libraries":

```markdown
- **webauthn** (py_webauthn): builds the passkey ceremonies' options and verifies the
  browser's answers, in `src_back/services/passkeys.py`. It brings `cbor2`, a Rust
  extension with wheels for macOS on Apple silicon, Linux, and Windows, so an Intel Mac
  needs Rust to install it. The tests answer the ceremonies with their own software
  authenticator rather than `soft-webauthn`, whose last release, in 2022, pins `fido2`
  below 2.0.
```

After the `Zustand` entry under "Frontend runtime libraries":

```markdown
- **`@simplewebauthn/browser`**: runs the browser's passkey prompt and the email field's
  autofill, and turns their binary answers into JSON, in `api/passkeys.ts` and
  `hooks/usePasskeyLogin.ts`. It has no dependencies and is about 4 KB gzipped, and only
  the lazy sign-in and Account pages import it, so it has no vendor chunk.
```

In `README.md`'s tree, the `api/` line becomes
`# Blueprints (health, auth, OAuth, passkeys, users, audit logs)`, which stays within 90
characters.

## Parallelism

- **Group A, backend**, sequential inside: the pin and the install first; then the model,
  `user.py`, `models/__init__.py`, and the migration (generate, review, `db upgrade`,
  `db check`); then `errors.py` and `auth.py`; then the schemas, the service, the routes,
  and the registration; then the software authenticator, the fixtures, and the tests.
- **Group B, frontend**, sequential inside: the npm install first; then the types,
  `client.ts`, `utils/passkeys.ts`, `api/passkeys.ts`, the schema, and the two hooks;
  then `useAuthFormState.ts`, `ProviderButtons.tsx`, `SignInOptions.tsx`, `Login.tsx`,
  `Passkeys.tsx`, `Account.tsx`, and `RecordSection.tsx`; then the tests. Every API call
  is mocked, so B needs nothing from A.
- **Group C, documentation**: independent of both. Its last act checks each name it cites
  (`rp_settings`, `CHALLENGE_TTL_SECONDS`, the session keys, the messages, `isSignInStep`,
  the fixtures) against what A and B wrote.
- A, B, and C run in parallel once A's and B's installs are done.

Implementers are Opus, as #27 records for this issue: a mistake in sign-in code can pass
tests written by the same model.

### Mutation checks

Run each on a scratch copy, with a timeout per run, and report a survivor rather than
patching over it. Each must turn at least one named test red.

Group A:

1. `count_sign_in_methods` without `len(user.passkeys)`: the count test, the
   password-account delete (its 204 becomes a 409), and the unlink-with-a-passkey test.
   The `passkey_user` 409 survives it, since a count of 0 is still at most 1.
2. `_take_challenge` without the account check: the other-account tests.
3. `_take_challenge` without the expiry check: the expired tests.
4. `_take_challenge` reading with `session.get` instead of `pop`: the replay and
   spend tests.
5. `rp_settings` returning `PUBLIC_BASE_URL` as the origin verbatim: the origin tests.
6. `verify_registration` without its key build: the off-curve test.
7. The registration `except` narrowed to
   `(WebAuthnException, KeyError, TypeError, ValueError)`: the not-a-map test raises
   `IndexError`. `_SIGN_IN_REJECTED` without `ValueError`: the `'A'` user-handle test and
   the saved-key test raise instead of refusing.
8. `backup_eligible` read from `credential_backed_up`: the eligible-but-not-backed-up
   case.
9. `_new_passkey` without `dict.fromkeys`: the repeated-transport test.
10. `_find_passkey` without the user-handle check: the user-handle tests.
11. `verify_authentication` leaving out each of its three writes in turn: the use,
    backup-state, and counter tests.
12. `require_user_verification=False` in either verify call: the two
    requires-user-verification tests. `UserVerificationRequirement.PREFERRED` in either
    options: the two options tests.
13. `delete_passkey` without `require_another_sign_in_method`: the 409 tests.
14. `_owned_passkey` searching every passkey: the other-account rename and delete tests.
15. Each `PASSKEY_AUDIT_TRAIL` call removed in turn: the audit tests.
16. `_options_response` without `Cache-Control`; `login_verify` without
    `complete_login`, then without its `InactiveAccountError` branch: the route tests.
17. `registration_options` without `exclude_credentials`, then with
    `ResidentKeyRequirement.PREFERRED`: the options tests.
18. `_save_new_passkey` without its `IntegrityError` branch: the duplicate tests.
19. `sign_count` as `Integer`, model and migration: the largest-counter test, on
    PostgreSQL only (Verification step 4). On SQLite it survives by design.
20. The credential-id cap removed: the 1,024-byte case of the cap test.
21. `rp_settings` without its `try`, or with `urlsplit` moved back above it: the
    does-not-parse test raises `ValueError`.
22. `_descriptor` without the known-transport filter: the stale-transport test raises.

Group B:

1. `SIGNED_IN_AUTH_PATHS` without `/v1/auth/passkeys`, then `PASSKEY_SIGN_IN_PATH`
   unchecked: the client tests.
2. `isUnder` matching only `${path}/`: the list-URL client test.
3. `handleAuthAction` without its null check: the Login dismissed-prompt test.
4. The unmount effect removed: the unmount-while-the-prompt-is-open test.
   `offerAutofill` without either `signal.aborted` check: the other unmount tests.
5. The autofill call without `useBrowserAutofill: true`: the autofill test.
6. The effect reading `run` instead of `runRef.current`: the rerender test. Its deps as
   `[offer, run]`: the loads-once test.
7. The refresh timer removed: the four-minute test. `setOffer` dropped from `signIn`'s
   `finally`: the restart-after-dismissal test. The cleanup's busy guard removed: the
   no-`cancelCeremony` assertion. The effect's busy early return removed: the no-new-offer
   assertion.
8. `signIn` without `autofillRef.current?.abort()`: the quick-click test.
9. `FALLBACK_MESSAGE` changed: the fallback assertion. `offerAutofill` calling `run`
   before the pick: the Login alert-survives-renewal test and the `run`-called-once case.
   The `.then` renewal removed: the failed-pick case.
10. `isCancelledCeremony` without the `NotAllowedError` case, then without the abort
    code: the cancellation tests.
11. `registrationFailure` without the excluded-device case: its test.
12. `SignInOptions` rendering the divider with nothing to offer: its test.
13. `Passkeys` without `addDisabledReason`: its test.
14. `RecordSection`'s `item?.id` read back into the closure: no Vitest test can fail,
    because Vitest runs without the compiler; Verification step 5 is the check.

## No other changes needed

- `WEBAUTHN_RP_NAME` and its fallback (`src_back/app.py:146-150`), its lines in
  `.env.example` and `.env.staging.example`, the `PUBLIC_BASE_URL` fallback and its
  warning (`app.py:188-209`), and the Compose files that pass both exist since #28.
- `require_another_sign_in_method` and `LAST_METHOD` need no change; the count does the
  work. `unlink_account` already calls the guard.
- The `X-Requested-With` hook covers the new POST, PUT, and DELETE routes; the axios
  client sends the header, and no route needs an exemption.
- `scripts/nginx-ssl.conf.template`: `^~ /api/v1/auth/` already covers the passkey POSTs.
- The audit history routes list `webauthn_credentials` once the trail registers it, and
  the admin Audit tab shows table names as they are.
- `vite.config.ts`: no vendor chunk for the library.
- `useSessionQueryCache` clears `['passkeys']` with every other query when the account
  changes.
- `docker/`, `scripts/`, the backups, and the restore drill: no new volume or upload
  column.

## Added during implementation

Chuck approved these on 2026-11-03, after the groups' mutation checks and the browser
check showed gaps that no listed test could fail:

- `test_passkeys.py` gains three guards:
    - `test_rp_settings_name_the_site_after_webauthn_rp_name`: a hard-coded RP name passed
      in CI, where neither `APP_NAME` nor `WEBAUTHN_RP_NAME` is set.
    - `test_verify_registration_saves_the_authenticators_counter`: saving 0 passed, since
      every test registered at 0; the guard registers at 7.
    - `test_verify_authentication_lets_a_database_failure_through`: a broad `except` at
      sign-in passed. The guard makes `_find_passkey` raise `OperationalError` and expects
      it to escape, so a database failure stays a 500, as departure 17 says.
- `usePasskeyLogin.test.tsx` gains "renews only once a picked passkey has finished signing
  in". With `void run(...)` in place of `await run(...)`, the renewal's options GET would
  carry the signed-out session cookie while the sign-in was in flight, and its answer
  could land last and sign the visitor out.
- `EntityList`'s rows reserve room for every action. At 375 px the browser check found a
  used passkey's row text running under its Edit icon in all three engines, because MUI
  pads a row with a `secondaryAction` for one 40 px button, and the passkey list is the
  first with two. `EntityRow` now sets `pr` to 16 px plus 40 px per action, and
  `EntityList.test.tsx` checks a two-action row's 96 px. Re-measured in all three engines
  at 375 and 1280 px, no text runs under Edit, and the Users list's one-action rows still
  fit.
- Two other survivors change nothing observable, so they have no test: dropping
  `!controller.signal.aborted` from the renewal costs at most one extra options request in
  a race, and `verify_authentication` without its missing-challenge return still refuses,
  because py_webauthn then rejects the challenge itself.

The browser check also showed:

- A virtual authenticator answers the sign-in page's autofill request by itself as soon as
  the page mounts, which proves the production build's autofill sign-in end to end.
  Picking from Chrome's suggestion with the keyboard cannot be driven, so that stays in
  step 6.
- After a successful passkey sign-in the page sends one more `GET /login/options` before
  it unmounts, because the offer renews once the sign-in settles. It costs a round trip
  and leaves an unused challenge in the session.
- The only console errors are the browsers' own network lines for the 401 from `/me` on a
  signed-out page load, which this change does not touch.
- Text with no break point, such as an email like
  `christopher.alexanderson@longcompanyexample.com` or a nickname of 64 letters without a
  space, still runs past its row at 375 px, under the Edit icon and 1 px beyond the
  viewport. `EntityList` has no wrap rule for row text, which predates this change.

## Verification

1. While editing, targeted runs only:

    ```bash
    .venv/bin/python -m pytest src_back/tests/test_passkeys.py \
      src_back/tests/test_passkeys_api.py src_back/tests/test_auth.py \
      src_back/tests/test_oauth_api.py src_back/tests/test_schemas.py --no-cov
    npx vitest run src_front/src/test/api src_front/src/test/utils/passkeys.test.ts \
      src_front/src/test/schemas/passkey.test.ts src_front/src/test/hooks \
      src_front/src/test/components/auth src_front/src/test/components/account \
      src_front/src/test/pages
    ```

2. The migration, on the dev database: `.venv/bin/flask --app src_back.app db upgrade`,
   then `db check`, which must report no new upgrade operations; then `db downgrade` (not
   `-1`, which Click reads as an option), `db upgrade`, and `db check` again.
3. At the end, in parallel: `npm run test`, `npm run lint -- --max-warnings=0`, and
   `npm run lint:py`. Then `npm run typecheck`, `npm run fallow`, `npm run lint:md`,
   `npx prettier --check .`, `npm run build`, `npm run test:scripts`,
   `.venv/bin/pip-audit -r requirements.txt`, and `npm audit --audit-level=high`, which
   CI runs. `bash scripts/tests/test-backend-image.sh` builds the backend image, which
   must install `cbor2` from a wheel and import the app.
4. PostgreSQL, where the counter and `bytea` columns differ from SQLite. Pick a free port
   and name the container for this check:

    ```bash
    docker run -d --rm --name issue-32-postgres -p 127.0.0.1:55432:5432 \
      -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app -e POSTGRES_DB=app postgres:16
    TEST_DATABASE_URL=postgresql://app:app@127.0.0.1:55432/app .venv/bin/python -m pytest
    docker rm -f issue-32-postgres
    ```

5. A browser check of the production build, all in the scratchpad and nothing committed.
   The React Compiler runs only in production builds, and #29's Account page crashed there
   while every test passed.
    - Build with `npm run build`. A scratch runner calls `create_app()` with
      `PUBLIC_BASE_URL='http://localhost:<port>'`, `SESSION_COOKIE_SAMESITE='Strict'`, a
      scratch SQLite file it fills with `db.create_all()`, and a non-placeholder
      `SECRET_KEY`, and serves `dist/` on that port. http is deliberate: `localhost` is a
      secure context, and Chrome refuses WebAuthn on a self-signed origin.
    - Playwright 1.64.1 from a scratch directory
      (`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm i playwright@1.64.1`, then
      `npx playwright install webkit firefox`).
    - Installed Chrome (`channel: 'chrome'`), with a CDP session that sends
      `WebAuthn.enable`, then `WebAuthn.addVirtualAuthenticator` with the protocol
      `ctap2`, the transport `internal`, and `hasResidentKey`, `hasUserVerification`,
      `isUserVerified`, and `automaticPresenceSimulation` all true:
      register with a password; add the passkey `Laptop` on the Account page, which lists
      it as never used; rename it, and reload; sign out, then sign in with the passkey
      button, which lands on Home; the Account page then shows when it was last used;
      delete it, add another, then open Delete and cancel. Sign out once more, focus the
      email field, and try to pick the passkey from Chrome's suggestion with the keyboard;
      record whether a virtual authenticator can drive the autofill, since step 6 covers
      it otherwise.
    - WebKit and Firefox, which Playwright gives no virtual authenticator: sign in with
      that account's password, open the Account page, open Rename and cancel, open
      Delete and cancel (#57's path), and load the sign-in page, which shows the passkey
      button.
    - In every browser: no console error, no route error boundary, and at 375 px neither
      page scrolls sideways.
    - Afterwards stop the runner, confirm no process holds the port, and delete the
      scratch files.
6. Chuck, by hand, before the PR leaves draft: Chrome's DevTools WebAuthn panel on the
   dev stack (`npm run docker:up`, then `npm run docker:url`), with Supports resident keys
   and Supports user verification ticked on the virtual authenticator, for the autofill
   pick and the button; and a real device over https with iCloud Keychain or Google
   Password Manager, through an https tunnel whose host is `PUBLIC_BASE_URL`, or on
   staging right after the merge.
