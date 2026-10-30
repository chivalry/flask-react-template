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
        self.context = context
        self.calls: list[object] = []
        self.messages: list[EmailMessage] = []
        CONNECTIONS.append(self)

    def starttls(self, context: ssl.SSLContext | None = None) -> None:
        self.context = context
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


@pytest.mark.parametrize('port', ['1', '65535'])
def test_settings_accept_the_lowest_and_highest_port(
    monkeypatch: pytest.MonkeyPatch,
    port: str,
) -> None:
    monkeypatch.setenv('SMTP_HOST', HOST)
    monkeypatch.setenv('SMTP_USERNAME', 'me@example.test')
    monkeypatch.setenv('SMTP_PORT', port)
    settings = smtp_settings_from_environment()
    assert settings is not None
    assert settings.port == int(port)


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


def test_send_puts_the_sender_in_from_when_the_username_differs() -> None:
    sender = 'Example App <app@mail.example.test>'
    [message] = _send(dataclasses.replace(ACCOUNT, sender=sender)).messages
    assert message['From'] == sender


def test_send_over_ssl_uses_smtp_ssl_with_a_context() -> None:
    smtp = _send(dataclasses.replace(ACCOUNT, port=465, security='ssl'))
    assert type(smtp) is FakeSmtpSsl
    assert smtp.opened == (HOST, 465, 30, True)
    assert smtp.calls == [
        ('login', 'me@example.test', 'app-password'),
        ('send', RECIPIENT, SUBJECT),
        'quit',
    ]


@pytest.mark.parametrize('security', ['starttls', 'ssl'])
def test_send_verifies_the_servers_certificate(security: str) -> None:
    context = _send(dataclasses.replace(ACCOUNT, security=security)).context
    assert context is not None
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname


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
