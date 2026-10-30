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
