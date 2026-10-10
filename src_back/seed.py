"""Database seed entry point; add seed logic to :func:`seed`.

``docker/entrypoint.sh`` runs ``python -m src_back.seed`` on every container
start, so whatever :func:`seed` inserts must be idempotent.
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
