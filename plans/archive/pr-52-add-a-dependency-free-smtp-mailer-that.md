# Issue #19: Add a dependency-free SMTP mailer that is off until configured

## Context

Three derived apps each wrote their own way to send mail, and the template has none, so
the fourth app would write a fourth. This ports hukilau's standard-library SMTP module
and its tests, read at hukilau `1a7fc99`, where the reminder job that used them lived
until 2269e92 removed both. Read them with
`git -C /Users/chuck/Projects/family/hukilau show 1a7fc99:src_back/mailer.py` (and
`src_back/tests/test_mailer.py`). Nothing in the template sends mail yet; #23's
scheduled jobs are the first expected caller.

hukilau's `mailer.py` already passes the template's Ruff, Ruff format, and pydoclint
unchanged (checked by piping it through them). Its test file fails Ruff's `ANN` rules 38
times, because hukilau's lint selects no `ANN`, so the test file below is rewritten with
annotations and typed recorder state. basedpyright checks `src_back/tests` too
(`pyproject.toml` `include`). An adversarial review ran every new Python file through
Ruff, Ruff format, pydoclint, the function-length check, basedpyright, and pytest on
Python 3.12.11 and 3.13.17 (24 tests, no uncovered line), and the new jq checks against
real `docker compose config` output; its findings are folded in below.

Decisions made with Chuck on 2026-10-30, beyond the issue text:

- `python -m src_back.mailer <address>` sends a test message through the configured
  account, so a server's settings can be checked before any feature sends mail. It
  follows `python -m src_back.seed`; its logic is a tested `main()`, and only the
  two-line `__main__` block falls under coverage's existing exclusion.
- Staging is documented, not enforced: `.env.staging.example` gets `SMTP_HOST=` with a
  warning, the two places that say to fill in every blank (that file's header and step
  3 of `ai/staging.md`) now except `SMTP_HOST`, and `ai/staging.md` lists mail among
  what sets staging apart. `scripts/copy-production.sh` copies production's accounts,
  so mail from staging would reach real people, the risk hukilau#21 recorded.

Choices this plan makes:

- The `Message-ID` names the sender's domain. `make_msgid()` defaults to
  `socket.getfqdn()`, which on Chuck's Mac returns
  `1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.ip6.arpa`, and in a
  container returns the container's random hostname. The SMTP host is the fallback for
  hand-built settings whose sender has no domain.
- `smtp_settings_from_environment()` requires the sender to be an email address with a
  local part and a domain, not only non-blank. hukilau accepted a username such as
  SendGrid's `apikey` or an Amazon SES access key as the From address, which the server
  refuses only at send time. One `ValueError` names both variables.
- A `SMTP_PORT` that is not a port number from 1 to 65535 raises `ValueError` naming the
  variable. `int()`'s own message names nothing, smtplib treats port 0 as its default
  port, and 70000 fails in the resolver with an error that names neither.
- The password is left out of `SmtpSettings`' repr (`field(repr=False)`), so a logged
  settings object never shows it.
- `Date` comes from `formatdate(localtime=True)`; the backend container runs in UTC, so
  the header reads `+0000` there.
- Compose passes `SMTP_SECURITY` with a blank fallback rather than hukilau's
  `starttls`, so the default lives only in the module.
- `conftest.py` gains an autouse `_clear_smtp_environment` beside
  `_clear_app_environment`, rather than hukilau's tests owning it: with a developer's
  `.env` configuring mail, any test that reached `send_email` without faking smtplib,
  such as a future job's, would send real mail. Every test now starts with mail off.

Kept from hukilau: `_open_connection` closes the connection when `starttls()` raises
an `SMTPException`, which is how a server without STARTTLS (`SMTPNotSupportedError`) or
one refusing it with `454` (`SMTPResponseException`) leaves the socket open. A failed
TLS handshake is an `ssl.SSLError`, an `OSError`, and the `SSLSocket` closes itself
(CPython `ssl.py`, `SSLSocket._create`), as hukilau#21 confirmed on 3.12 and 3.13.

Known edge, kept: `smtplib.SMTP.__exit__` raises `SMTPResponseException` when the server
answers `QUIT` with anything but 221, after the message was accepted, so `send_email`
would report a delivered message as failed. Servers answer 221; a caller that retries on
`EmailDeliveryError` should tolerate a rare duplicate.

## Branch

`issue-19-add-a-dependency-free-smtp-mailer-that` — already checked out; PR #52 exists.

## Change

**15 files**, 2 of them new: `src_back/mailer.py` (new),
`src_back/tests/test_mailer.py` (new), `src_back/tests/conftest.py`, `.env.example`,
`.env.staging.example`, `docker-compose.yml`, `docker/docker-compose.prod.yml`,
`scripts/provision.sh`, `scripts/tests/test-provision.sh`,
`scripts/tests/test-compose-config.sh`, `ai/project.md`, `ai/staging.md`,
`ai/domain.md`, `tools.md`, `README.md`.

Line numbers are those of the files before any edit, so place each change by its quoted
neighbor. Every block inserted into an existing file keeps one blank line between it
and its neighbors, as the surrounding sections have; in Python, `npm run format:py` sets
the blank lines around top-level definitions.

### src_back/mailer.py — new

Keep `import smtplib` and call `smtplib.SMTP` and `smtplib.SMTP_SSL` through the module:
the tests replace those attributes, which a `from smtplib import SMTP` would bypass.

```python
"""Plain-text email through the SMTP account in the ``SMTP_*`` variables.

Mail is off until ``SMTP_HOST`` is set: :func:`smtp_settings_from_environment` returns
``None`` while it is blank, and a caller then skips sending. Only the standard library
is used, so any provider that speaks SMTP works, from a mailbox with an app password,
such as Gmail or iCloud, to a transactional service.

A feature that sends mail reads the settings where it sends, skips sending when they
are ``None``, and handles :class:`EmailDeliveryError`::

    settings = smtp_settings_from_environment()
    if settings is not None:
        send_email(settings, user.email, subject, body)

``python -m src_back.mailer <address>`` sends a test message through the account.
"""

import argparse
import os
import smtplib
import ssl
import sys
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

SMTP_SECURITY_MODES = ('starttls', 'ssl', 'none')
SMTP_TIMEOUT_SECONDS = 30
TEST_SUBJECT = 'SMTP test message'
TEST_BODY = 'The SMTP_* settings work: this message was sent through them.\n'


class EmailDeliveryError(Exception):
    """The mail server refused the message or could not be reached."""


@dataclass(frozen=True)
class SmtpSettings:
    """Where and how to send mail.

    Attributes:
        host: The SMTP server.
        port: Its port.
        security: ``starttls``, ``ssl``, or ``none``.
        username: The login, or blank to send without one.
        password: The login's password, left out of the repr so a logged settings
            object never shows it.
        sender: The From address, optionally with a display name, such as
            ``Example App <app@example.com>``.
    """

    host: str
    port: int
    security: str
    username: str
    password: str = field(repr=False)
    sender: str


def smtp_settings_from_environment() -> SmtpSettings | None:
    """Read the SMTP settings from the ``SMTP_*`` variables.

    Returns:
        The settings, or ``None`` when ``SMTP_HOST`` is blank and email is off.

    Raises:
        ValueError: If ``SMTP_SECURITY`` is not a known mode, ``SMTP_PORT`` is not a
            port number, or the sender, ``SMTP_FROM`` or else ``SMTP_USERNAME``, is not
            an email address.
    """
    host = os.environ.get('SMTP_HOST', '').strip()
    if not host:
        return None
    security = os.environ.get('SMTP_SECURITY', '').strip() or 'starttls'
    if security not in SMTP_SECURITY_MODES:
        modes = ', '.join(SMTP_SECURITY_MODES)
        raise ValueError(f'SMTP_SECURITY must be one of: {modes}.')
    port = os.environ.get('SMTP_PORT', '').strip()
    if port and not (port.isdecimal() and 0 < int(port) < 65536):
        raise ValueError('SMTP_PORT must be a port number from 1 to 65535.')
    username = os.environ.get('SMTP_USERNAME', '').strip()
    sender = os.environ.get('SMTP_FROM', '').strip() or username
    if not _sender_domain(sender):
        raise ValueError(
            'SMTP_FROM, or SMTP_USERNAME when SMTP_FROM is blank, '
            'must be an email address.'
        )
    default_port = 465 if security == 'ssl' else 587
    return SmtpSettings(
        host=host,
        port=int(port) if port else default_port,
        security=security,
        username=username,
        password=os.environ.get('SMTP_PASSWORD', ''),
        sender=sender,
    )


def send_email(settings: SmtpSettings, recipient: str, subject: str, body: str) -> None:
    """Send one plain-text message.

    The message carries the ``Date`` header RFC 5322 requires and a ``Message-ID`` at
    the sender's domain, or at the SMTP host when the sender has none. The default
    domain would be this machine's name, a random ID inside a container.

    Args:
        settings: The SMTP account to send through.
        recipient: The To address.
        subject: The subject line.
        body: The plain-text body.

    Raises:
        EmailDeliveryError: If the server refuses the message or cannot be reached.
    """
    message = EmailMessage()
    message['From'] = settings.sender
    message['To'] = recipient
    message['Subject'] = subject
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid(
        domain=_sender_domain(settings.sender) or settings.host
    )
    message.set_content(body)
    try:
        with _open_connection(settings) as smtp:
            if settings.username:
                smtp.login(settings.username, settings.password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailDeliveryError(str(exc)) from exc


def main(arguments: list[str] | None = None) -> int:
    """Send a test message through the account the ``SMTP_*`` variables configure.

    ``python -m src_back.mailer <address>`` runs it, so a server's settings can be
    checked before any feature sends mail.

    Args:
        arguments: The command-line arguments after the program name; ``None`` reads
            them from ``sys.argv``.

    Returns:
        ``0`` once the server accepts the message; ``1`` when mail is off, a setting
        is invalid, or delivery fails.
    """
    parser = argparse.ArgumentParser(description='Send a test message through SMTP_*.')
    parser.add_argument('recipient', help='The address to send the test message to.')
    recipient = parser.parse_args(arguments).recipient
    try:
        settings = smtp_settings_from_environment()
        if settings is None:
            print('SMTP_HOST is blank, so mail is off.', file=sys.stderr)
            return 1
        send_email(settings, recipient, TEST_SUBJECT, TEST_BODY)
    except (ValueError, EmailDeliveryError) as exc:
        print(f'No test message sent: {exc}', file=sys.stderr)
        return 1
    print(f'Sent a test message to {recipient}.')
    return 0


def _sender_domain(sender: str) -> str:
    """Return the domain of the email address in a From value.

    Args:
        sender: The From value, with or without a display name.

    Returns:
        The part after the address's last ``@``, or an empty string when the value
        holds no address with both a local part and a domain.
    """
    local, _, domain = parseaddr(sender)[1].rpartition('@')
    return domain if local else ''


def _open_connection(settings: SmtpSettings) -> smtplib.SMTP:
    """Connect to the server, upgrading the connection for ``starttls``.

    Args:
        settings: The SMTP account to connect to.

    Returns:
        The open connection, ready to log in and send.

    Raises:
        smtplib.SMTPException: If the STARTTLS upgrade fails; the connection is
            closed first.
    """
    context = ssl.create_default_context()
    if settings.security == 'ssl':
        return smtplib.SMTP_SSL(
            settings.host, settings.port, timeout=SMTP_TIMEOUT_SECONDS, context=context
        )
    smtp = smtplib.SMTP(settings.host, settings.port, timeout=SMTP_TIMEOUT_SECONDS)
    if settings.security == 'starttls':
        try:
            smtp.starttls(context=context)
        except smtplib.SMTPException:
            smtp.close()
            raise
    return smtp


if __name__ == '__main__':
    from dotenv import load_dotenv

    load_dotenv()
    raise SystemExit(main())
```

Why the pieces sit where they do:

- `load_dotenv()` runs only in the `__main__` block, so on the host the command reads
  `.env` (python-dotenv walks up from `src_back/` to the repository root), while in a
  container, where `.dockerignore` keeps `.env` out, Compose supplies the variables.
  Calling it inside `main()` would refill variables the tests just cleared, and leak
  them into later tests, since monkeypatch does not undo what `load_dotenv` sets.
- `pyproject.toml`'s `exclude_lines` already lists `if __name__ == .__main__.:`, which
  excludes the whole block, as for `src_back/seed.py`.
- All three `raise ValueError` statements stay in `smtp_settings_from_environment`
  itself: pydoclint's DOC502 rejects a `Raises:` section on a function whose body
  raises nothing, so moving them into helpers would force dropping the section.
- `_sender_domain` tests the local part. `'apikey'.rpartition('@')` is
  `('', '', 'apikey')`, so the third part alone would accept a bare username, and
  `parseaddr('@example.com')` returns `('', '@example.com')` on 3.12.11 and 3.13.17.
  `parseaddr('me@')` returns `('', '')` on both, so a dangling `@` counts as no
  address too.
- `port.isdecimal()` guards `int(port)`, which the `and` evaluates only for digits.

### src_back/tests/conftest.py — every test starts with mail off

`conftest.py` imports `src_back.app`, whose `load_dotenv()` puts a developer's `SMTP_*`
values into `os.environ` for the whole session. hukilau's settings tests fail on any
machine whose `.env` configures mail, and a test of a future feature could send real
mail. After `PNG_BYTES` (line 26), add:

```python
# The variables src_back/mailer.py reads; _clear_smtp_environment unsets every one.
SMTP_VARIABLES = (
    'SMTP_HOST',
    'SMTP_PORT',
    'SMTP_SECURITY',
    'SMTP_USERNAME',
    'SMTP_PASSWORD',
    'SMTP_FROM',
)
```

After `_clear_app_environment` (lines 54-58), add:

```python
@pytest.fixture(autouse=True)
def _clear_smtp_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # src_back.app loads .env at import, where a developer's SMTP_* settings would let a
    # test send real mail. Every test starts with mail off, and a mailer test sets what
    # it needs.
    for name in SMTP_VARIABLES:
        monkeypatch.delenv(name, raising=False)
```

### src_back/tests/test_mailer.py — new

`CONNECTIONS` and `FAILURES` sit below the classes because module-level annotations are
evaluated at import on 3.12 and 3.13, so `list[FakeSmtp]` needs the class defined
first; the methods read them only when called.

```python
import dataclasses
import re
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Self

import pytest

from src_back.mailer import (
    TEST_SUBJECT,
    EmailDeliveryError,
    SmtpSettings,
    main,
    send_email,
    smtp_settings_from_environment,
)

HOST = 'smtp.example.test'
RECIPIENT = 'you@example.test'
SUBJECT = 'Example App: 1 follow-up due'
BODY = 'You have 1 follow-up due.\n'
SENDER_ERROR = 'SMTP_FROM, or SMTP_USERNAME when SMTP_FROM is blank, must be an email'

ACCOUNT = SmtpSettings(
    host=HOST,
    port=587,
    security='starttls',
    username='me@example.test',
    password='app-password',
    sender='me@example.test',
)


class FakeSmtp:
    """Stand in for ``smtplib.SMTP``, recording what the mailer asks of it."""

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        context: ssl.SSLContext | None = None,
    ) -> None:
        if 'connect' in FAILURES:
            raise OSError('Network is unreachable')
        self.opened = (host, port, timeout, context is not None)
        self.calls: list[object] = []
        self.messages: list[EmailMessage] = []
        CONNECTIONS.append(self)

    def starttls(self, context: ssl.SSLContext | None = None) -> None:
        self.calls.append('starttls')
        if 'starttls' in FAILURES:
            raise smtplib.SMTPException('no TLS')

    def login(self, username: str, password: str) -> None:
        self.calls.append(('login', username, password))

    def send_message(self, message: EmailMessage) -> None:
        self.calls.append(('send', message['To'], message['Subject']))
        self.messages.append(message)
        if 'send' in FAILURES:
            raise smtplib.SMTPException('Mailbox unavailable')

    def close(self) -> None:
        self.calls.append('close')

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.calls.append('quit')


class FakeSmtpSsl(FakeSmtp):
    """The same recorder standing in for ``smtplib.SMTP_SSL``, told apart by type."""


# The steps of the fake connection that fail: 'connect', 'starttls', or 'send'.
FAILURES: set[str] = set()
# The connections the mailer opened in the current test, oldest first.
CONNECTIONS: list[FakeSmtp] = []


@pytest.fixture(autouse=True)
def _fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    FAILURES.clear()
    CONNECTIONS.clear()
    monkeypatch.setattr(smtplib, 'SMTP', FakeSmtp)
    monkeypatch.setattr(smtplib, 'SMTP_SSL', FakeSmtpSsl)


def _only_connection() -> FakeSmtp:
    [smtp] = CONNECTIONS
    return smtp


def _send(settings: SmtpSettings = ACCOUNT) -> FakeSmtp:
    send_email(settings, RECIPIENT, SUBJECT, BODY)
    return _only_connection()


# -- Settings -----------------------------------------------------------------


def test_settings_are_none_without_a_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('SMTP_USERNAME', 'me@example.test')
    assert smtp_settings_from_environment() is None
    monkeypatch.setenv('SMTP_HOST', '   ')
    assert smtp_settings_from_environment() is None


def test_settings_default_to_starttls_on_587_with_the_username_as_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('SMTP_HOST', f' {HOST} ')
    monkeypatch.setenv('SMTP_USERNAME', 'me@example.test')
    monkeypatch.setenv('SMTP_PASSWORD', 'app-password')
    assert smtp_settings_from_environment() == ACCOUNT


def test_ssl_defaults_to_465_and_an_explicit_port_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('SMTP_HOST', HOST)
    monkeypatch.setenv('SMTP_SECURITY', 'ssl')
    monkeypatch.setenv('SMTP_FROM', 'Example App <app@example.test>')
    expected = SmtpSettings(
        host=HOST,
        port=465,
        security='ssl',
        username='',
        password='',
        sender='Example App <app@example.test>',
    )
    assert smtp_settings_from_environment() == expected
    monkeypatch.setenv('SMTP_PORT', ' 2465 ')
    assert smtp_settings_from_environment() == dataclasses.replace(expected, port=2465)


def test_settings_reject_an_unknown_security_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('SMTP_HOST', HOST)
    monkeypatch.setenv('SMTP_USERNAME', 'me@example.test')
    monkeypatch.setenv('SMTP_SECURITY', 'tls')
    with pytest.raises(
        ValueError, match='SMTP_SECURITY must be one of: starttls, ssl, none'
    ):
        smtp_settings_from_environment()


@pytest.mark.parametrize('port', ['submission', '0', '65536'])
def test_settings_reject_a_port_that_is_not_a_port_number(
    monkeypatch: pytest.MonkeyPatch,
    port: str,
) -> None:
    monkeypatch.setenv('SMTP_HOST', HOST)
    monkeypatch.setenv('SMTP_USERNAME', 'me@example.test')
    monkeypatch.setenv('SMTP_PORT', port)
    with pytest.raises(ValueError, match='SMTP_PORT must be a port number'):
        smtp_settings_from_environment()


@pytest.mark.parametrize(
    ('sender', 'username'),
    [
        pytest.param('', '', id='neither'),
        pytest.param('', 'apikey', id='username-not-an-address'),
        pytest.param('Example App', 'me@example.test', id='from-not-an-address'),
        pytest.param('@example.test', '', id='from-without-a-local-part'),
    ],
)
def test_settings_need_a_sender_address(
    monkeypatch: pytest.MonkeyPatch,
    sender: str,
    username: str,
) -> None:
    monkeypatch.setenv('SMTP_HOST', HOST)
    monkeypatch.setenv('SMTP_FROM', sender)
    monkeypatch.setenv('SMTP_USERNAME', username)
    with pytest.raises(ValueError, match=SENDER_ERROR):
        smtp_settings_from_environment()


def test_settings_keep_the_password_out_of_their_repr() -> None:
    assert 'app-password' not in repr(ACCOUNT)


# -- Sending ------------------------------------------------------------------


def test_send_upgrades_with_starttls_then_logs_in_and_sends() -> None:
    smtp = _send()
    assert type(smtp) is FakeSmtp
    assert smtp.opened == (HOST, 587, 30, False)
    assert smtp.calls == [
        'starttls',
        ('login', 'me@example.test', 'app-password'),
        ('send', RECIPIENT, SUBJECT),
        'quit',
    ]
    [message] = smtp.messages
    assert message['From'] == 'me@example.test'
    assert message.get_content() == BODY


def test_send_dates_the_message_and_names_the_sender_domain_in_its_id() -> None:
    # The Date header has whole seconds, so the lower bound drops the microseconds.
    earliest = datetime.now(UTC).replace(microsecond=0)
    [message] = _send().messages
    assert earliest <= parsedate_to_datetime(str(message['Date'])) <= datetime.now(UTC)
    assert re.fullmatch(r'<[^<>@\s]+@example\.test>', str(message['Message-ID']))


def test_send_names_the_host_in_the_id_when_the_sender_has_no_domain() -> None:
    [message] = _send(dataclasses.replace(ACCOUNT, sender='mailer')).messages
    assert str(message['Message-ID']).endswith(f'@{HOST}>')


def test_send_over_ssl_uses_smtp_ssl_with_a_context() -> None:
    smtp = _send(dataclasses.replace(ACCOUNT, port=465, security='ssl'))
    assert type(smtp) is FakeSmtpSsl
    assert smtp.opened == (HOST, 465, 30, True)
    assert smtp.calls == [
        ('login', 'me@example.test', 'app-password'),
        ('send', RECIPIENT, SUBJECT),
        'quit',
    ]


def test_send_with_no_security_and_no_username_skips_starttls_and_login() -> None:
    smtp = _send(
        dataclasses.replace(ACCOUNT, port=1025, security='none', username='', password='')
    )
    assert type(smtp) is FakeSmtp
    assert smtp.opened == (HOST, 1025, 30, False)
    assert smtp.calls == [('send', RECIPIENT, SUBJECT), 'quit']


@pytest.mark.parametrize(
    ('failure', 'cause', 'detail'),
    [
        pytest.param('send', smtplib.SMTPException, 'Mailbox unavailable', id='refused'),
        pytest.param('connect', OSError, 'Network is unreachable', id='network'),
    ],
)
def test_send_wraps_smtp_and_network_errors(
    failure: str,
    cause: type[Exception],
    detail: str,
) -> None:
    FAILURES.add(failure)
    with pytest.raises(EmailDeliveryError, match=detail) as raised:
        send_email(ACCOUNT, RECIPIENT, SUBJECT, BODY)
    assert type(raised.value.__cause__) is cause


def test_a_failed_starttls_closes_the_connection() -> None:
    FAILURES.add('starttls')
    with pytest.raises(EmailDeliveryError, match='no TLS'):
        send_email(ACCOUNT, RECIPIENT, SUBJECT, BODY)
    smtp = _only_connection()
    assert type(smtp) is FakeSmtp
    assert smtp.calls == ['starttls', 'close']


# -- Test message -------------------------------------------------------------


def test_main_sends_a_test_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv('SMTP_HOST', HOST)
    monkeypatch.setenv('SMTP_USERNAME', 'me@example.test')
    assert main([RECIPIENT]) == 0
    [message] = _only_connection().messages
    assert message['To'] == RECIPIENT
    assert message['Subject'] == TEST_SUBJECT
    assert capsys.readouterr().out == f'Sent a test message to {RECIPIENT}.\n'


def test_main_says_mail_is_off_without_a_host(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([RECIPIENT]) == 1
    assert CONNECTIONS == []
    assert capsys.readouterr().err == 'SMTP_HOST is blank, so mail is off.\n'


def test_main_reports_an_invalid_setting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv('SMTP_HOST', HOST)
    monkeypatch.setenv('SMTP_USERNAME', 'apikey')
    assert main([RECIPIENT]) == 1
    assert CONNECTIONS == []
    assert capsys.readouterr().err.startswith('No test message sent: SMTP_FROM, or ')


def test_main_reports_a_refused_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv('SMTP_HOST', HOST)
    monkeypatch.setenv('SMTP_USERNAME', 'me@example.test')
    FAILURES.add('send')
    assert main([RECIPIENT]) == 1
    assert capsys.readouterr().err == 'No test message sent: Mailbox unavailable\n'
```

These cover every acceptance criterion: a blank host returns `None`; an unknown
`SMTP_SECURITY` and a missing sender raise `ValueError` naming the variable; the fake
records the login when a username is set, the `From`, `To`, `Subject`, `Date`, and
`Message-ID` headers, and a refused message mapped to `EmailDeliveryError`. Every line
of the module except the `__main__` block runs, which keeps `npm run test:back` at
100%.

### .env.example — the SMTP block

Insert after line 51 (`WEBAUTHN_RP_NAME=`) and its blank line, before the
`Production only` section, since development uses it too. The header is 82 characters,
like the others (`awk '/^# ---/ {print length($0)}' .env.example`):

```text
# --- Outgoing mail (src_back/mailer.py) -----------------------------------------
# A blank SMTP_HOST turns email off, and code that sends mail skips it. SMTP_SECURITY
# is starttls (port 587), ssl (465), or none; SMTP_PORT overrides the port. Examples:
#   Gmail: SMTP_HOST=smtp.gmail.com, port 587, an app password.
#   iCloud: SMTP_HOST=smtp.mail.me.com, port 587, an app-specific password.
# SMTP_FROM defaults to SMTP_USERNAME; set it when the username is not an email address.
# It may carry a display name: Example App <app@example.com>. Staging leaves SMTP_HOST
# blank, since its accounts are copies of production's (.env.staging.example).
SMTP_HOST=
SMTP_PORT=
SMTP_SECURITY=starttls
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
```

### .env.staging.example — keep mail off

Replace lines 2-4 of the header, which tell the operator to fill in every blank:

```text
# (ai/staging.md). Copy this file to .env in the staging clone, chmod 600 it, and fill
# in every blank but SMTP_HOST. Generate each secret with `openssl rand -hex 32`; none
# may match production's.
```

Insert after line 45 (`ADMIN_PASSWORD=`) and its blank line. Only `SMTP_HOST` appears,
so nothing invites filling in the rest. `scripts/tests/test-deploy.sh:130-139` requires
every key here to exist in `.env.example`, which it does:

```text
# --- Outgoing mail (src_back/mailer.py) -----------------------------------------
# Leave SMTP_HOST blank, which keeps mail off: scripts/copy-production.sh copies
# production's accounts here, so mail from staging would reach real people.
SMTP_HOST=
```

### docker-compose.yml and docker/docker-compose.prod.yml — pass them through

No Compose file uses `env_file:`, and `.dockerignore` keeps `.env` out of the image, so
the backend sees only what its `environment:` lists. Add these six lines to the backend
`environment:` in `docker-compose.yml` after line 38 (`ADMIN_PASSWORD`), and the same
six to `docker/docker-compose.prod.yml` after line 28 (`ADMIN_PASSWORD`). The
production override restates its variables even where the base already has them, as it
does for `WEBAUTHN_RP_NAME` and `ADMIN_*`:

```yaml
      SMTP_HOST: ${SMTP_HOST:-}
      SMTP_PORT: ${SMTP_PORT:-}
      SMTP_SECURITY: ${SMTP_SECURITY:-}
      SMTP_USERNAME: ${SMTP_USERNAME:-}
      SMTP_PASSWORD: ${SMTP_PASSWORD:-}
      SMTP_FROM: ${SMTP_FROM:-}
```

Each uses `:-`, so `test-compose-config.sh` needs no new placeholder export: its line
22 comment covers only the bare `${VAR}` names the production override requires.

### scripts/provision.sh — write blank SMTP values

In the heredoc, insert after line 112 (`ADMIN_PASSWORD=$ADMIN_PASS`) and line 113's
blank line, before the `Loopback ports` section. The heredoc is unquoted, and this
block holds no `$` or backtick:

```text
# --- Outgoing mail (src_back/mailer.py) -----------------------------------------
# A blank SMTP_HOST keeps mail off. SMTP_SECURITY is starttls (port 587), ssl (465), or
# none; SMTP_FROM defaults to SMTP_USERNAME and must be an email address.
SMTP_HOST=
SMTP_PORT=
SMTP_SECURITY=starttls
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
```

After line 147 (`echo "    steps that use them."`), add:

```bash
  echo "    Mail stays off until SMTP_HOST and the other SMTP_* values are filled in."
```

### scripts/tests/test-provision.sh — check the new lines

Rewrite the comment at lines 134-136 to:

```bash
# A fresh server gets a mode 600 .env with the clone's name, the domain, the three
# generated secrets, every retention setting, and blank mail settings, and the Docker
# apt source for its release.
```

After line 151 (`assert_contains '^DEPLOY_BRANCH=main$' "$ENV_FILE"`), add:

```bash
assert_contains '^SMTP_HOST=$' "$ENV_FILE"
assert_contains '^SMTP_PORT=$' "$ENV_FILE"
assert_contains '^SMTP_SECURITY=starttls$' "$ENV_FILE"
assert_contains '^SMTP_USERNAME=$' "$ENV_FILE"
assert_contains '^SMTP_PASSWORD=$' "$ENV_FILE"
assert_contains '^SMTP_FROM=$' "$ENV_FILE"
```

After line 183 (`assert_contains 'Log out and back in' "$OUTPUT"`), add:

```bash
assert_contains 'Mail stays off until SMTP_HOST' "$OUTPUT"
```

The key loop at lines 161-166 then also proves each `SMTP_*` key is in `.env.example`.
No `openssl rand` call is added, so the counting stub's secrets keep their values.

### scripts/tests/test-compose-config.sh — the variables reach the backend

Replace the header comment's lines 5-6 with these three, so its list names the new
check:

```bash
# backend, that neither stack overrides the image's user, that both pass the .env's
# SMTP_* variables to the backend, blank when unset, and what the production stack
# must keep: loopback-only ports and no database port; a backend that runs
```

Extend the `unset` at lines 25-26, so a developer's shell cannot supply the values:

```bash
unset COMPOSE_FILE GUNICORN_WORKERS SESSION_COOKIE_SECURE SESSION_COOKIE_SAMESITE \
  APP_ENVIRONMENT SMTP_HOST SMTP_PORT SMTP_SECURITY SMTP_USERNAME SMTP_PASSWORD SMTP_FROM
```

After line 45 (the `prod-staging` render), render both stacks with every variable set:

```bash
(
  export SMTP_HOST=smtp.example.com SMTP_PORT=2525 SMTP_SECURITY=ssl \
    SMTP_USERNAME=mailer@example.com SMTP_PASSWORD=app-password \
    SMTP_FROM=noreply@example.com
  render > "$TEST_DIR/dev-smtp.json"
  render -f docker-compose.yml -f docker/docker-compose.prod.yml \
    > "$TEST_DIR/prod-smtp.json"
)
```

After line 108 (the `prod-staging` `APP_ENVIRONMENT` check), add:

```bash
# Mail stays off until the .env names a host, and every SMTP_* value it gives reaches
# the backend in both stacks.
for stack in dev prod; do
  check "$stack" '.services.backend.environment | [.SMTP_HOST, .SMTP_PORT,
    .SMTP_SECURITY, .SMTP_USERNAME, .SMTP_PASSWORD, .SMTP_FROM] | all(. == "")' \
    'blank SMTP_* variables, which leave mail off'
  check "$stack-smtp" '.services.backend.environment | .SMTP_HOST == "smtp.example.com"
    and .SMTP_PORT == "2525" and .SMTP_SECURITY == "ssl"
    and .SMTP_USERNAME == "mailer@example.com" and .SMTP_PASSWORD == "app-password"
    and .SMTP_FROM == "noreply@example.com"' \
    'the SMTP_* variables its .env gives passed through to the backend'
done
```

A missing key renders as `null`, which fails both checks, so dropping a line from
`docker-compose.yml` fails the dev stack's checks. It does not fail the production
stack's, because the override restates the same keys and Compose merges `environment`
key by key. The override's six lines only restate the base file's, so no check sees
them, and dropping one from the override fails nowhere; they follow the override's
convention of restating its variables.
Compose renders environment values as strings, as the `GUNICORN_WORKERS == "4"` check
already relies on.

### ai/project.md — the module and the rule

In Project Structure, after line 26 (`extensions.py`), add:

```markdown
    - `mailer.py` - plain-text email through the SMTP account in `SMTP_*`, standard
      library only; off while `SMTP_HOST` is blank
```

In Environment, insert this paragraph and command between line 133 (the end of the
`.env.staging.example` paragraph) and line 135 (the `load_dotenv()` paragraph), with a
blank line on each side:

````markdown
Mail is off until `SMTP_HOST` is set: `smtp_settings_from_environment()` in
`src_back/mailer.py` returns `None` while it is blank, and code that sends mail then
skips it. `SMTP_SECURITY` is `starttls` (the default, port 587), `ssl` (465), or `none`,
and `SMTP_PORT` overrides the port. The sender is `SMTP_FROM`, or `SMTP_USERNAME` when
that is blank, and must be an email address. `send_email()` sends one plain-text
message and raises `EmailDeliveryError` when the server refuses it or cannot be reached.
Staging keeps `SMTP_HOST` blank, because its accounts are copies of production's, and a
server provisioned before the mailer has no `SMTP_*` lines in its `.env`, which leaves
mail off there until they are added. To check the settings, send a test message.
Compose hands `.env`'s values to a container only when it creates one, so on a server,
redeploy (`npm run deploy`) after changing `SMTP_*`, then run it in the backend
container:

```bash
.venv/bin/python -m src_back.mailer you@example.com      # locally, reading .env
docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml --env-file .env \
  exec -T backend python -m src_back.mailer you@example.com   # on a server
```
````

Then replace the last line of the `load_dotenv()` paragraph (line 138):

```markdown
`src_back/tests/test_app.py` do; `conftest.py` clears `APP_ENVIRONMENT` and the `SMTP_*`
variables for every test, so no test sends mail through a developer's account.
```

### ai/staging.md — mail stays off on staging

In the Overview list, after the session-cookie item (lines 21-22), add:

```markdown
- mail, which stays off: `SMTP_HOST` is blank, because `scripts/copy-production.sh`
  fills staging with production's accounts, and mail to them would reach real people;
```

Replace step 3 of "Setting up staging" (lines 67-70), which says to fill in every
blank:

```markdown
3. Fill in every blank in `.env` except `SMTP_HOST`, which stays blank so staging sends
   no mail. Generate each secret with `openssl rand -hex 32`, and repeat
   `POSTGRES_PASSWORD` inside `DATABASE_URL`. Set both `CORS_ALLOWED_ORIGINS` and
   `PUBLIC_BASE_URL` to `https://<DOMAIN>`. `PRODUCTION_DIR` must name production's
   clone, and `STAGING_HTPASSWD` the file the next step creates.
```

### ai/domain.md — the new fixture

In Test Fixtures, after the `_clear_app_environment` item (lines 43-44), add:

```markdown
- `_clear_smtp_environment` - an autouse fixture that clears the `SMTP_*` variables, so
  every test starts with mail off and a developer's `.env` cannot make one send mail
```

### tools.md — no mail library

Replace the Backend runtime libraries intro (lines 35-36):

```markdown
Installed from `requirements.txt` into the backend image and into `.venv`, except
watchdog, which only the dev stack's backend image gets, and the standard-library
modules in the last entry, which come with Python.
```

Replace the python-dotenv item (lines 76-79):

```markdown
- **python-dotenv**: loads `.env` when `src_back/app.py` is imported, so the `flask`
  command, the seed, and pytest read the same settings on the host;
  `python -m src_back.mailer`, which never imports the app, loads it itself. In the
  containers Compose supplies the variables instead, and `.dockerignore` keeps `.env`
  out of the image.
```

At the end of the list, after the watchdog item (line 87), add:

```markdown
- **`smtplib` and `email`**: the standard-library modules `src_back/mailer.py` sends
  mail with. No mail package is installed: these work with any provider that speaks
  SMTP, while a vendor SDK, such as SendGrid's, would tie the app to one.
```

### README.md — project layout

In the layout tree, after line 213 (`extensions.py`), add a line whose comment column
matches its neighbors:

```text
│   ├── mailer.py      # Plain-text SMTP mail; off while SMTP_HOST is blank
```

## Parallelism

Implementer model: Sonnet 5.5 (#27). Every file's content is fixed above, so the three
groups share nothing and run at once:

- **Backend**: `src_back/mailer.py`, `src_back/tests/test_mailer.py`, and
  `src_back/tests/conftest.py`. Then `npm run format:py` and
  `.venv/bin/python -m pytest src_back/tests/test_mailer.py --no-cov`.
- **Configuration**: `.env.example`, `.env.staging.example`, both Compose files,
  `scripts/provision.sh`, `scripts/tests/test-provision.sh`, and
  `scripts/tests/test-compose-config.sh`. Then `bash scripts/tests/test-provision.sh`,
  `bash scripts/tests/test-compose-config.sh`, and `bash scripts/tests/test-deploy.sh`
  (the staging-key check), plus
  `npx prettier --check docker-compose.yml docker/docker-compose.prod.yml`.
- **Docs**: `ai/project.md`, `ai/staging.md`, `ai/domain.md`, `tools.md`, and
  `README.md`. Then `npm run lint:md` and
  `npx prettier --check ai/project.md ai/staging.md ai/domain.md tools.md README.md`.

Sequential, after all three: the full checks in one parallel batch, then the end-to-end
run in Verification.

## No other changes needed

- `requirements.txt`: the module uses only the standard library and python-dotenv,
  which is already a runtime dependency.
- `docker/backend.Dockerfile` already copies `src_back/`, and the dev override's file
  watch already syncs it.
- `docker-compose.override.yml` sets no environment; Mailpit is left for a project
  that wants it, as the issue's Notes say.
- `scripts/up.sh` and `scripts/worktree-setup.sh` copy `.env.example`, or `main`'s
  `.env`, whole, so the new keys pass through; `scripts/deploy.sh` checks no `SMTP_*`
  key, and a blank `SMTP_HOST` deploys as before.
- `scripts/copy-production.sh` stays as it is: staging's mail is documented, not
  enforced.
- CI's pytest step sets no `SMTP_*` variable, and the tests clear them anyway.
- `src_back/app.py` gains nothing: nothing sends mail until a feature such as #23's
  jobs calls the module.
- `ai/conventions.md` stays as it is.

## Verification

1. Targeted, during the groups: the commands listed under Parallelism.
2. Full, at the end, in one parallel batch: `npm run test`, `npm run lint`,
   `npm run lint:py`, `npm run lint:md`, and `npm run test:scripts`. Both suites must
   stay at 100% coverage, and `test-compose-config.sh` must run rather than skip.
3. End to end against a real SMTP server, Mailpit `v1.31.6` (released 2026-10-15),
   with every `SMTP_*` set on the command line so a developer's `.env` cannot add a
   login (`load_dotenv` never overrides a variable that is set, even blank):

    ```bash
    docker run --rm -d --name mailpit-issue-19 -p 127.0.0.1:1025:1025 \
      -p 127.0.0.1:8025:8025 axllent/mailpit:v1.31.6
    SMTP_HOST=127.0.0.1 SMTP_PORT=1025 SMTP_SECURITY=none SMTP_USERNAME= \
      SMTP_PASSWORD= SMTP_FROM='Example App <app@example.test>' \
      .venv/bin/python -m src_back.mailer you@example.test
    curl -s http://127.0.0.1:8025/api/v1/message/latest/raw
    ```

    Expect `Sent a test message to you@example.test.` and exit status 0, and a raw
    message with `From: Example App <app@example.test>`, `To`, `Subject`, a `Date`
    within the last minute, and `Message-ID: <...@example.test>`.
4. Edge cases against the same server, rerunning the command with one variable changed:
    - `SMTP_SECURITY=starttls`: expect exit status 1 and `No test message sent:` with
      the STARTTLS error, since Mailpit started without a certificate offers no
      STARTTLS. That is the path where `_open_connection` closes the socket.
    - `SMTP_PORT=1026`: nothing listens there, so expect exit status 1 and
      `No test message sent:` with the refused connection.
    - `SMTP_HOST=`: expect exit status 1 and `SMTP_HOST is blank, so mail is off.`
5. Through Compose, which the documented server command relies on. With the dev stack
   up, join Mailpit to the stack's network, rebuild and recreate the backend with the
   variables (blank login, so a developer's `.env` cannot add one; Mailpit offers no
   AUTH by default), send, and find the message in Mailpit; then recreate the backend
   without them:

    ```bash
    docker network connect "$(grep '^COMPOSE_PROJECT_NAME=' .env | cut -d= -f2)_default" \
      mailpit-issue-19
    SMTP_HOST=mailpit-issue-19 SMTP_PORT=1025 SMTP_SECURITY=none SMTP_USERNAME= \
      SMTP_PASSWORD= SMTP_FROM=app@example.test docker compose up -d --build backend
    docker compose exec -T backend python -m src_back.mailer you@example.test
    docker compose up -d backend
    ```

6. Clean up with `docker rm -f mailpit-issue-19`, and confirm `docker ps -a` no longer
   lists it.
