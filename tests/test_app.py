import threading
import time

from fastapi.testclient import TestClient
import pytest
from app import main
from app.cloud import Cloud, XiaomiSession, allowed_url
from app.upstream import XiaomiCloudConnector

ORIGIN = 'http://localhost:8080'


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setattr(main, 'ORIGIN', ORIGIN)
    with main.lock:
        for s in main.sessions.values():
            s.erase()
        main.sessions.clear()
        main.attempts.clear()
    yield


@pytest.fixture
def client():
    with TestClient(main.app, base_url=ORIGIN) as client:
        yield client


def seed(client, **kwargs):
    session = main.Session(**kwargs)
    main.sessions['test-session'] = session
    client.cookies.set('xiaomi_session', 'test-session', path='/api')
    return session


def test_cross_visitor_isolation(client):
    seed(client, state='ready', devices=[{'token': 'FAKE-ONLY'}])
    assert client.get('/api/session').json()['devices'][0]['token'] == 'FAKE-ONLY'
    with TestClient(main.app, base_url=ORIGIN) as stranger:
        assert stranger.get('/api/session').status_code == 401
        assert stranger.get('/api/qr').status_code == 401


def test_csrf_and_host_checks(client):
    seed(client)
    assert client.delete('/api/session').status_code == 403
    assert client.delete('/api/session', headers={'Origin': 'https://evil.test'}).status_code == 403
    assert client.get('/api/session', headers={'Host': 'evil.test'}).status_code == 400
    assert client.get('/api/session', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert 'test-session' in main.sessions


def test_expiry_erases_results(client):
    s = seed(client, expires=time.monotonic()-1, image=b'qr', devices=[{'token': 'FAKE'}])
    assert client.get('/api/session').status_code == 401
    assert s.cancelled and not s.image and not s.devices
    assert not main.sessions


def test_forget_clears_session_and_cookie(client):
    s = seed(client, state='ready', devices=[{'token': 'FAKE'}])
    r = client.delete('/api/session', headers={'Origin': ORIGIN})
    assert r.status_code == 204
    assert 'Max-Age=0' in r.headers['set-cookie']
    assert s.cancelled and not s.devices
    assert client.get('/api/session').status_code == 401


def test_cookie_security_and_consent(client, monkeypatch):
    def instant(session, region):
        main.workers.release()
    monkeypatch.setattr(main, 'run', instant)
    assert client.post('/api/session', headers={'Origin': ORIGIN}, json={'region':'de','consent':False}).status_code == 400
    assert client.post('/api/session', headers={'Origin': ORIGIN}, json={'region':'invalid','consent':True}).status_code == 400
    r = client.post('/api/session', headers={'Origin': ORIGIN}, json={'region':'de','consent':True})
    cookie = r.headers['set-cookie']
    assert r.status_code == 200
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/api' in cookie
    assert 'expires_in' in r.json() and 'token' not in r.json()


def test_https_cookie_and_security_headers(monkeypatch):
    monkeypatch.setattr(main, 'ORIGIN', 'https://keys.example.com')
    monkeypatch.setattr(main, 'run', lambda s, r: main.workers.release())
    with TestClient(main.app, base_url='https://keys.example.com') as client:
        r = client.post('/api/session', headers={'Origin':'https://keys.example.com'}, json={'region':'de','consent':True})
        assert 'Secure' in r.headers['set-cookie']
        assert r.headers['cache-control'] == 'no-store'
        assert "frame-ancestors 'none'" in r.headers['content-security-policy']
        assert 'strict-transport-security' in r.headers


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(main, 'run', lambda s, r: main.workers.release())
    for _ in range(10):
        assert client.post('/api/session', headers={'Origin': ORIGIN}, json={'region':'de','consent':True}).status_code == 200
    assert client.post('/api/session', headers={'Origin': ORIGIN}, json={'region':'de','consent':True}).status_code == 429


def test_cancel_during_fetch_cannot_restore_secrets(client, monkeypatch):
    entered, finish = threading.Event(), threading.Event()
    class FakeCloud:
        def start(self): return b'qr', 'image/png'
        def wait(self, cancelled): return True
        def devices(self, regions, cancelled):
            entered.set(); finish.wait(2)
            return [{'token':'FAKE'}], []
        def close(self): pass
    monkeypatch.setattr(main, 'Cloud', FakeCloud)
    s = seed(client)
    assert main.workers.acquire(False)
    worker = threading.Thread(target=main.run, args=(s,'de'))
    worker.start(); assert entered.wait(2)
    client.delete('/api/session', headers={'Origin':ORIGIN})
    finish.set(); worker.join(2)
    assert not worker.is_alive() and not s.devices and s.cancelled


def test_upstream_errors_are_redacted(client, monkeypatch, caplog):
    class BrokenCloud:
        def start(self): raise RuntimeError('SECRET-MUST-NOT-APPEAR')
        def close(self): pass
    monkeypatch.setattr(main, 'Cloud', BrokenCloud)
    s = seed(client)
    assert main.workers.acquire(False)
    main.run(s,'de')
    r = client.get('/api/session')
    assert r.json()['state'] == 'error'
    assert 'SECRET-MUST-NOT-APPEAR' not in r.text + caplog.text


def test_qr_not_available_after_login(client):
    s = seed(client, state='waiting', image=b'not-a-real-qr')
    assert client.get('/api/qr').content == b'not-a-real-qr'
    s.state = 'ready'
    assert client.get('/api/qr').status_code == 404


@pytest.mark.parametrize('url', [
    'http://account.xiaomi.com/x', 'https://account.xiaomi.com.evil.test/x',
    'https://127.0.0.1/x', 'https://account.xiaomi.com@evil.test/x',
    'https://account.xiaomi.com:444/x', 'https://evil.test',
])
def test_untrusted_xiaomi_urls_rejected(url):
    assert not allowed_url(url)
    import requests
    prepared = requests.Request('GET',url).prepare()
    with pytest.raises(ValueError):
        XiaomiSession().send(prepared)


def test_crypto_roundtrip_and_signature():
    import base64
    key = base64.b64encode(b'0123456789abcdef').decode()
    payload = '{"device":"synthetic-only"}'
    encrypted = XiaomiCloudConnector.encrypt_rc4(key,payload)
    assert XiaomiCloudConnector.decrypt_rc4(key,encrypted).decode() == payload
    assert len(XiaomiCloudConnector.generate_nonce(1234567890)) == 16


def test_regional_xiaomi_endpoints():
    assert allowed_url('https://eu.lp.account.xiaomi.com/longPolling/login')
    assert allowed_url('https://eu.account.xiaomi.com/qr')
    assert allowed_url('https://de.api.io.mi.com/app')
    assert not allowed_url('https://eu.account.xiaomi.com.evil.test/qr')


def test_no_arbitrary_assets_or_oversized_posts(client):
    assert client.get('/assets/main.py').status_code == 404
    assert client.post('/api/session', headers={'Origin':ORIGIN}, content='x'*2049).status_code == 413
    assert client.get('/').status_code == 200
    assert client.get('/assets/app.js').status_code == 200


def test_page_assets_work_from_a_file_and_the_web_server(client):
    from html.parser import HTMLParser
    from pathlib import Path
    class Assets(HTMLParser):
        def __init__(self):
            super().__init__()
            self.paths = []
        def handle_starttag(self, tag, attributes):
            attrs = dict(attributes)
            if tag == 'script':
                self.paths.append(attrs['src'])
            if tag == 'link' and attrs.get('rel') == 'stylesheet':
                self.paths.append(attrs['href'])
    parser = Assets()
    parser.feed(client.get('/').text)
    assert len(parser.paths) == 2
    for path in parser.paths:
        assert path.startswith('./')
        local = main.STATIC / path
        assert local.is_file()
        response = client.get('/' + path.removeprefix('./'))
        assert response.status_code == 200
        assert response.content == local.read_bytes()
