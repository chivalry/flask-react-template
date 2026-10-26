"""Database seed entry point; :func:`seed` runs each step, starting with the first admin.

``docker/entrypoint.sh`` runs ``python -m src_back.seed`` on every container
start and stops the container when it exits non-zero, so a genuine failure such
as a bad import or a database error is loud. Whatever :func:`seed` inserts must
therefore be idempotent, and a seed that depends on optional input, such as a
password from the environment, should log and return rather than raise when
that input is absent.

Every step runs inside one application context and only flushes; :func:`seed` commits
once, after the last step, so a step that fails leaves the database as it was. A step that
skips its work prints one line saying why.

:func:`_seed_admin` is the only step so far. A project adds its own steps to :func:`seed`,
before the commit. Lookup rows nobody edits, such as states, go in a step that inserts
only the rows missing by their natural key. Rows an admin can rename or delete, such as
categories, go in a step that returns unless the table is empty; keyed on a name an
admin can change, a renamed row would come back on the next start, as a renamed admin
would without the check in :func:`_seed_admin`. Development samples go in a step that
returns unless ``FLASK_ENV`` is ``development`` and the table is empty. Keep the rows
themselves in a ``seed_data.py`` module of plain data that never touches the database.
"""

import os

from flask import Flask

from src_back.extensions import db
from src_back.models import Role, User
from src_back.services.auth import find_user_by_email


def seed(app: Flask) -> None:
    """Run every seed step inside one application context, then commit once.

    Steps only flush, so a step that raises leaves nothing committed.

    Args:
        app: The configured application whose database should be seeded.
    """
    with app.app_context():
        _seed_admin()
        db.session.commit()


def _seed_admin() -> None:
    """Create the first admin account from ``ADMIN_EMAIL`` and ``ADMIN_PASSWORD``.

    Skips, printing why, when either variable is missing or blank, when any admin
    account exists, active or not, or when an account already has the email in any
    letter case. The admin check is what makes the bootstrap run once. An admin can
    change their own email on the Users screen, so looking for the email alone would
    create the account again, with the password from the environment, on the next start
    after a rename. Nothing removes the last active admin through the API, so an
    existing admin means the bootstrap already ran.

    It never changes or promotes an existing account: a later ``ADMIN_PASSWORD`` change
    resets nobody, and an account someone registered under ``ADMIN_EMAIL`` stays a plain
    user.
    """
    email = os.environ.get('ADMIN_EMAIL', '').strip()
    password = os.environ.get('ADMIN_PASSWORD', '')
    if not email or not password.strip():
        print('Skipping admin seed: ADMIN_EMAIL and ADMIN_PASSWORD are not set.')
        return
    if db.session.query(User.id).filter_by(role=Role.admin).first() is not None:
        print('An admin account already exists; skipping admin seed.')
        return
    if find_user_by_email(email) is not None:
        print(f'Account {email} already exists; skipping admin seed.')
        return
    user = User(email=email, role=Role.admin, is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    print(f'Seeded admin {user.email}.')


if __name__ == '__main__':
    from src_back.app import create_app

    seed(create_app())
