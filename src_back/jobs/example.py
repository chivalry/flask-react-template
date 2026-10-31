"""Example job: count the accounts that can sign in.

``python -m src_back.jobs.example`` runs it once; on the server, enabling
``<APP_NAME>-job@example.timer`` runs it daily (``ai/project.md``, Scheduled Jobs). It
only reads, so enabling it changes nothing. A real job does its work where
:func:`_count_active_accounts` is called, and the commit after it saves that work in one
transaction; a job with an outside effect, such as an email, commits after each one
instead, so a failure later in the run neither repeats it nor loses the record of it.
"""

from flask import Flask

from src_back.app import create_app
from src_back.extensions import db
from src_back.models import User


def main(app: Flask | None = None) -> int:
    """Run the job once and print one line saying what it did.

    Args:
        app: The application to run against; ``None`` builds one with
            ``create_app()``, as ``python -m src_back.jobs.example`` does.

    Returns:
        ``0`` once the work is committed. An exception propagates instead, so the
        process exits 1, the systemd unit fails, and its alert fires.
    """
    if app is None:
        app = create_app()
    with app.app_context():
        active = _count_active_accounts()
        db.session.commit()
    print(f'Example job counted active accounts: {active}.')
    return 0


def _count_active_accounts() -> int:
    """Count the accounts that are not deactivated.

    Returns:
        The number of active accounts.
    """
    return db.session.query(User).filter_by(is_active=True).count()


if __name__ == '__main__':
    raise SystemExit(main())
