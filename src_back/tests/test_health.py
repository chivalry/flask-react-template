from flask.testing import FlaskClient


def test_health(client: FlaskClient) -> None:
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'ok'
