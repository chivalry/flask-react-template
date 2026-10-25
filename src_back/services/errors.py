"""Exceptions services raise when a request breaks a business rule.

Route handlers catch them and answer with the matching envelope from
:mod:`src_back.utils`, such as :func:`~src_back.utils.conflict` for a 409.
"""


class DuplicateRecordError(Exception):
    """A unique natural key, such as a name or an email, is already taken (409)."""
