"""SQLAlchemy models, re-exported so ``from src_back.models import X`` keeps working.

Importing this package registers every table on the shared metadata, which is what
``db.create_all()`` and ``flask db migrate`` rely on, so a new model module is imported
here and its classes are added to ``__all__``.
"""

from src_back.models.base import BaseMixin
from src_back.models.user import Role, User

__all__ = ['BaseMixin', 'Role', 'User']
