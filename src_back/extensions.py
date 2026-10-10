"""Flask extension singletons shared across the application.

Each extension is constructed unbound here and attached to the application
inside :func:`src_back.app.create_app`, so that modules can import them
without triggering a circular import back through the app factory.
"""

from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base shared by every model.

    Models subclass this directly and use SQLAlchemy 2.0 annotated mapping
    (``Mapped[]`` and ``mapped_column``). Passing it to
    :class:`~flask_sqlalchemy.SQLAlchemy` puts its metadata under Flask-SQLAlchemy
    and Flask-Migrate, so ``db.create_all()`` and ``flask db migrate`` see every
    model that inherits from it.
    """


db = SQLAlchemy(model_class=Base)
migrate = Migrate()
login_manager = LoginManager()
