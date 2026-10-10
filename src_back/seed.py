"""Database seed entry point; add seed logic to :func:`seed`.

``docker/entrypoint.sh`` runs ``python -m src_back.seed`` on every container
start and stops the container when it exits non-zero, so a genuine failure such
as a bad import or a database error is loud. Whatever :func:`seed` inserts must
therefore be idempotent, and a seed that depends on optional input, such as a
password from the environment, should log and return rather than raise when
that input is absent.
"""

from flask import Flask


def seed(app: Flask) -> None:
    """Populate the database with initial rows.

    This template defines none; replace the body with inserts that skip rows
    which already exist so the seed is safe to run more than once.

    Args:
        app: The configured application whose database should be seeded.
    """
    with app.app_context():
        print('No seed data defined.')


if __name__ == '__main__':
    from src_back.app import create_app

    seed(create_app())
