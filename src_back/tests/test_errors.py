from src_back.services.errors import RecordInUseError


def test_record_in_use_error_keeps_message_and_count() -> None:
    exc = RecordInUseError('In use.', 3)
    assert str(exc) == 'In use.'
    assert exc.count == 3
