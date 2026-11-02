from src_back.services.errors import OAuthError, RecordInUseError


def test_record_in_use_error_keeps_message_and_count() -> None:
    exc = RecordInUseError('In use.', 3)
    assert str(exc) == 'In use.'
    assert exc.count == 3


def test_oauth_error_keeps_its_code() -> None:
    exc = OAuthError('expired')
    assert exc.code == 'expired'
    assert str(exc) == 'expired'
