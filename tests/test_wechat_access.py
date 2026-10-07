import time

import pytest

from cricket import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            'TESTING': True,
            'SECRET_KEY': 'isolated-desktop-test',
            'ADMIN_PASSWORD': 'isolated-password',
            'DATABASE': str(tmp_path / 'desktop.sqlite3'),
            'PUBLIC_BASE_URL': 'https://example.test',
            'DEMO_MODE': False,
            'WECHAT_DESKTOP_ENABLED': True,
        }
    )


def test_desktop_requires_current_admin_session(app):
    client = app.test_client()
    response = client.get('/admin/wechat/access')
    assert response.status_code == 302
    assert response.headers['Location'] == '/admin/login'
    with client.session_transaction() as session:
        session['admin_until'] = time.time() + 60
    response = client.get('/admin/wechat/access', headers={'Origin': 'https://example.test'})
    assert response.status_code == 204
    assert response.headers['Cache-Control'] == 'no-store'
    with client.session_transaction() as session:
        session['admin_until'] = time.time() - 1
    assert client.get('/admin/wechat/access').status_code == 302


@pytest.mark.parametrize('flag', ['disabled', 'demo', 'foreign_origin', 'null_origin'])
def test_desktop_denies_disabled_demo_and_cross_origin(app, flag):
    client = app.test_client()
    with client.session_transaction() as session:
        session['admin_until'] = time.time() + 60
    headers = {}
    if flag == 'disabled':
        app.config['WECHAT_DESKTOP_ENABLED'] = False
    elif flag == 'demo':
        app.config['DEMO_MODE'] = True
    else:
        headers['Origin'] = 'null' if flag == 'null_origin' else 'https://elsewhere.test'
    response = client.get('/admin/wechat/access', headers=headers)
    assert response.status_code == (404 if flag in ('disabled', 'demo') else 403)
