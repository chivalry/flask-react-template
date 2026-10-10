import io
import uuid

import pytest
from flask import Blueprint, jsonify
from marshmallow import Schema, ValidationError, fields
from werkzeug.datastructures import FileStorage

from src_back.tests.conftest import PNG_BYTES
from src_back.utils import (
    DEFAULT_PER_PAGE,
    MAX_PER_PAGE,
    admin_required,
    bad_request,
    conflict,
    dump_or_404,
    forbidden,
    new_uuid,
    not_found,
    now,
    paginate,
    paginate_and_dump,
    pagination_args,
    parse_request_json,
    require_parent,
    unauthorized,
    unprocessable_entity,
    validate_image_file,
)


class NameSchema(Schema):
    name = fields.Str(required=True)


class Named:
    def __init__(self, name):
        self.name = name


# -- error helpers ------------------------------------------------------------


@pytest.mark.parametrize(
    ('helper', 'status', 'default_message'),
    [
        (bad_request, 400, 'Bad request'),
        (unauthorized, 401, 'Unauthorized'),
        (forbidden, 403, 'Forbidden'),
        (not_found, 404, 'Not found'),
        (conflict, 409, 'Conflict'),
        (unprocessable_entity, 422, 'Unprocessable entity'),
    ],
)
def test_error_helpers_return_default_and_custom_messages(
    app, helper, status, default_message
):
    with app.test_request_context('/'):
        response, code = helper()
        assert code == status
        assert response.get_json() == {'error': default_message}
        response, code = helper('Custom message')
        assert code == status
        assert response.get_json() == {'error': 'Custom message'}


# -- paginate -----------------------------------------------------------------


def test_paginate_first_page():
    result = paginate(list(range(50)), page=1, per_page=20)
    assert result['items'] == list(range(20))
    assert result['total'] == 50
    assert result['page'] == 1
    assert result['pages'] == 3
    assert result['per_page'] == 20


def test_paginate_second_page():
    result = paginate(list(range(50)), page=2, per_page=20)
    assert result['items'] == list(range(20, 40))


def test_paginate_last_page_partial():
    result = paginate(list(range(25)), page=2, per_page=20)
    assert result['items'] == list(range(20, 25))
    assert result['pages'] == 2


def test_paginate_beyond_last_page_is_empty():
    result = paginate(list(range(5)), page=99, per_page=10)
    assert result['items'] == []
    assert result['total'] == 5


def test_paginate_empty_list():
    result = paginate([], page=1, per_page=20)
    assert result['items'] == []
    assert result['total'] == 0
    assert result['pages'] == 0


def test_paginate_zero_per_page_reports_one_page():
    result = paginate([1, 2, 3], page=1, per_page=0)
    assert result['items'] == []
    assert result['pages'] == 1


# -- pagination_args ----------------------------------------------------------


def test_pagination_args_defaults(app):
    with app.test_request_context('/'):
        assert pagination_args() == (1, DEFAULT_PER_PAGE)


def test_pagination_args_from_query(app):
    with app.test_request_context('/?page=3&per_page=50'):
        assert pagination_args() == (3, 50)


def test_pagination_args_clamps_per_page_to_maximum(app):
    with app.test_request_context('/?per_page=999'):
        _, per_page = pagination_args()
    assert per_page == MAX_PER_PAGE


def test_pagination_args_clamps_page_and_per_page_below_one(app):
    with app.test_request_context('/?page=0&per_page=0'):
        assert pagination_args() == (1, 1)


def test_pagination_args_invalid_values_fall_back_to_defaults(app):
    with app.test_request_context('/?page=abc&per_page=xyz'):
        assert pagination_args() == (1, DEFAULT_PER_PAGE)


# -- parse_request_json -------------------------------------------------------


def test_parse_request_json_returns_loaded_data(app):
    with app.test_request_context('/', method='POST', json={'name': 'Test'}):
        assert parse_request_json(NameSchema()) == {'name': 'Test'}


def test_parse_request_json_invalid_payload_raises_validation_error(app):
    with app.test_request_context('/', method='POST', json={}):
        with pytest.raises(ValidationError):
            parse_request_json(NameSchema())


def test_parse_request_json_treats_non_object_body_as_empty(app):
    with app.test_request_context('/', method='POST', json=[1, 2, 3]):
        with pytest.raises(ValidationError):
            parse_request_json(NameSchema())


def test_parse_request_json_partial_allows_missing_required_fields(app):
    with app.test_request_context('/', method='PUT', json={}):
        assert parse_request_json(NameSchema(), partial=True) == {}


# -- dump_or_404 and paginate_and_dump ----------------------------------------


def test_dump_or_404_serializes_a_record(app):
    with app.test_request_context('/'):
        response, status = dump_or_404(Named('hello'), NameSchema())
    assert status == 200
    assert response.get_json() == {'name': 'hello'}


def test_dump_or_404_answers_not_found_for_none(app):
    with app.test_request_context('/'):
        response, status = dump_or_404(None, NameSchema())
    assert status == 404
    assert response.get_json() == {'error': 'Not found'}


def test_paginate_and_dump_serializes_the_requested_page(app):
    items = [Named(f'item-{i}') for i in range(30)]
    with app.test_request_context('/?page=2&per_page=10'):
        response, status = paginate_and_dump(items, NameSchema())
    assert status == 200
    body = response.get_json()
    assert body['page'] == 2
    assert body['total'] == 30
    assert body['items'] == [{'name': f'item-{i}'} for i in range(10, 20)]


def test_paginate_and_dump_merges_extra_fields(app):
    with app.test_request_context('/'):
        response, status = paginate_and_dump(
            [Named('a')], NameSchema(), extra_fields={'total_amount': '12.34'}
        )
    assert status == 200
    assert response.get_json()['total_amount'] == '12.34'


# -- require_parent -----------------------------------------------------------


def test_require_parent_returns_none_when_parent_exists(app):
    with app.test_request_context('/'):
        assert require_parent(lambda _: object(), 1) is None


def test_require_parent_answers_not_found_when_parent_is_missing(app):
    with app.test_request_context('/'):
        result = require_parent(lambda _: None, 1)
    assert result is not None
    response, status = result
    assert status == 404


# -- validate_image_file ------------------------------------------------------


def test_validate_image_file_accepts_valid_png_file(app):
    file = FileStorage(stream=io.BytesIO(PNG_BYTES), filename='photo.png')
    with app.test_request_context('/'):
        assert validate_image_file(file) is None


@pytest.mark.parametrize(
    ('payload', 'filename'),
    [(PNG_BYTES, 'notes.txt'), (b'not an image', 'photo.png')],
)
def test_validate_image_file_rejects_bad_extension_or_bytes(app, payload, filename):
    file = FileStorage(stream=io.BytesIO(payload), filename=filename)
    with app.test_request_context('/'):
        rejection = validate_image_file(file)
    assert rejection is not None
    response, status = rejection
    assert status == 400
    assert response.get_json() == {'error': 'Invalid file type'}


def test_validate_image_file_rejects_file_when_seek_raises_oserror(app):
    class FileWithFailingSeek:
        filename = 'photo.png'

        def read(self, size):
            return PNG_BYTES[:size]

        def seek(self, position):
            raise OSError('seek failed')

    with app.test_request_context('/'):
        rejection = validate_image_file(FileWithFailingSeek())
    assert rejection is not None
    _, status = rejection
    assert status == 400


# -- admin_required -----------------------------------------------------------


def _register_admin_view(app):
    bp = Blueprint('admin_only', __name__)

    @bp.get('/admin-only')
    @admin_required
    def admin_view():
        return jsonify({'ok': True})

    app.register_blueprint(bp)


def _login(client, email, password):
    client.post('/api/v1/auth/login', json={'email': email, 'password': password})


def test_admin_required_allows_admin(app, client, admin_user):
    _register_admin_view(app)
    _login(client, admin_user.email, 'adminpass123')
    r = client.get('/admin-only')
    assert r.status_code == 200
    assert r.get_json() == {'ok': True}


def test_admin_required_forbids_regular_user(app, client, user):
    _register_admin_view(app)
    _login(client, user.email, 'password123')
    r = client.get('/admin-only')
    assert r.status_code == 403
    assert r.get_json() == {'error': 'Admin access required.'}


def test_admin_required_rejects_anonymous_caller(app, client):
    _register_admin_view(app)
    r = client.get('/admin-only')
    assert r.status_code == 401
    assert r.get_json() == {'error': 'Unauthorized'}


# -- misc ---------------------------------------------------------------------


def test_now_returns_timezone_aware_datetime():
    assert now().tzinfo is not None


def test_new_uuid_returns_string_parseable_as_uuid():
    value = new_uuid()
    assert len(value) == 36
    assert str(uuid.UUID(value)) == value
