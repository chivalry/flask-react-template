"""Typed access to the signed-in user.

Flask-Login's ``current_user`` reaches basedpyright as ``LocalProxy[Any | None]``:
reading ``role`` or ``id`` through it goes unchecked, and it cannot be passed where a
parameter is declared ``user: User``. Behind ``@login_required`` the proxy always
resolves to a real ``User``, so this module re-exports it under that type. Runtime
behavior is unchanged: the object is still Flask-Login's proxy.

Code that decides for itself whether anyone is signed in keeps importing from
``flask_login``: :func:`src_back.utils.admin_required` checks ``is_authenticated``,
so for it the value may genuinely be anonymous.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src_back.models import User

    current_user: User
else:
    from flask_login import current_user

__all__ = ['current_user']
