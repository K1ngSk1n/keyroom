import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
import os
import json
import secrets
import threading
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from .cloud import Cloud, REGIONS

ORIGIN = os.getenv('PUBLIC_ORIGIN', 'http://localhost:8080').rstrip('/')
TTL = 600
MAX_ACTIVE = 8
STATIC = Path(__file__).parent / 'static'
lock = threading.RLock()
sessions = {}
attempts = {}
workers = threading.BoundedSemaphore(MAX_ACTIVE)


@dataclass
class Session:
    expires: float = field(default_factory=lambda: time.monotonic() + TTL)
    state: str = 'starting'
    image: bytes = b''
    kind: str = 'image/png'
    devices: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    cancelled: bool = False

    def expired(self):
        return self.cancelled or time.monotonic() >= self.expires

    def erase(self):
        self.cancelled = True
        self.image = b''
        self.devices.clear()
        self.warnings.clear()


def cleanup():
    with lock:
        for key, session in list(sessions.items()):
            if session.expired():
                session.erase()
                del sessions[key]
        now = time.monotonic()
        for ip in list(attempts):
            attempts[ip] = [t for t in attempts[ip] if now - t < 900]
            if not attempts[ip]:
                del attempts[ip]


async def sweeper():
    while True:
        await asyncio.sleep(5)
        cleanup()


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(sweeper())
    yield
    task.cancel()
    with lock:
        for session in sessions.values():
            session.erase()
        sessions.clear()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware('http')
async def protections(request, call_next):
    # One explicit origin; no reflected Host, X-Forwarded-Host, or CORS trust.
    if request.headers.get('host') != urlsplit(ORIGIN).netloc:
        return Response(status_code=400)
    if request.method in ('POST', 'DELETE') and request.headers.get('origin') != ORIGIN:
        return Response(status_code=403)
    if request.headers.get('sec-fetch-site') == 'cross-site' and request.url.path.startswith('/api/'):
        return Response(status_code=403)
    try:
        length = int(request.headers.get('content-length', '0'))
    except ValueError:
        return Response(status_code=400)
    if request.method == 'POST' and ('content-length' not in request.headers or 'transfer-encoding' in request.headers):
        return Response(status_code=411)
    if length < 0 or length > 2048:
        return Response(status_code=413)
    response = await call_next(request)
    response.headers.update({
        'Cache-Control': 'no-store', 'Pragma': 'no-cache',
        'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
        'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
        'X-Frame-Options': 'DENY',
    })
    if ORIGIN.startswith('https://'):
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response


def current(request):
    cleanup()
    with lock:
        session = sessions.get(request.cookies.get('xiaomi_session', ''))
        if session is None or session.expired():
            raise HTTPException(401, 'Session ended. Start again to sign in.')
        return session


def run(session, region):
    cloud = None
    try:
        cloud = Cloud()
        image, kind = cloud.start()
        with lock:
            if session.expired():
                return
            session.image, session.kind, session.state = image, kind, 'waiting'
        if not cloud.wait(session.expired):
            with lock:
                if not session.expired():
                    session.state = 'expired'
                    session.image = b''
            return
        with lock:
            if session.expired():
                return
            session.state, session.image = 'fetching', b''
        devices, warnings = cloud.devices(REGIONS if region == 'all' else (region,), session.expired)
        with lock:
            if not session.expired():
                session.devices, session.warnings, session.state = devices, warnings, 'ready'
    except Exception:
        # Do not log exception text: upstream errors can contain tokens/URLs.
        with lock:
            if not session.expired():
                session.state, session.image = 'error', b''
    finally:
        if cloud:
            cloud.close()
        workers.release()


class Start(BaseModel):
    model_config = ConfigDict(extra='forbid')
    region: str
    consent: bool


@app.post('/api/session')
def start(body: Start, request: Request):
    if body.region not in (*REGIONS, 'all') or body.consent is not True:
        raise HTTPException(400, 'Choose a region and accept session processing.')
    cleanup()
    ip = request.client.host if request.client else 'unknown'
    with lock:
        if len(attempts) >= 4096 and ip not in attempts:
            raise HTTPException(503, 'Service busy. Try later.')
        history = attempts.setdefault(ip, [])
        if len(history) >= 10:
            raise HTTPException(429, 'Too many sign-in attempts. Try again in 15 minutes.')
        if len(sessions) >= 64 or not workers.acquire(blocking=False):
            raise HTTPException(503, 'All sign-in slots are busy. Try shortly.')
        history.append(time.monotonic())
        old = sessions.pop(request.cookies.get('xiaomi_session', ''), None)
        if old:
            old.erase()
        token = secrets.token_urlsafe(32)
        session = Session()
        sessions[token] = session
        threading.Thread(target=run, args=(session, body.region), daemon=True).start()
    response = JSONResponse({'state': 'starting', 'expires_in': TTL})
    response.set_cookie('xiaomi_session', token, max_age=TTL, httponly=True,
                        secure=ORIGIN.startswith('https://'), samesite='strict', path='/api')
    return response


@app.get('/api/session')
def status(request: Request):
    session = current(request)
    with lock:
        return {'state': session.state, 'expires_in': max(0, int(session.expires-time.monotonic())),
                'devices': list(session.devices), 'warnings': list(session.warnings)}


@app.get('/api/qr')
def qr(request: Request):
    session = current(request)
    with lock:
        if session.state != 'waiting' or not session.image:
            raise HTTPException(404)
        return Response(session.image, media_type=session.kind)


@app.delete('/api/session')
def forget(request: Request):
    with lock:
        session = sessions.pop(request.cookies.get('xiaomi_session', ''), None)
        if session:
            session.erase()
    response = Response(status_code=204)
    response.delete_cookie('xiaomi_session', path='/api')
    return response


@app.get('/healthz')
def health():
    return {'ok': True}


@app.get('/')
def index():
    return FileResponse(STATIC / 'index.html')


@app.get('/assets/{name}')
def assets(name: str):
    if name not in ('app.js', 'style.css'):
        raise HTTPException(404)
    return FileResponse(STATIC / name)


@app.get('/source')
def source_archive():
    archive = STATIC / 'keyroom-source.zip'
    if not archive.is_file():
        raise HTTPException(503, 'Source archive has not been packaged for this build.')
    return FileResponse(archive, filename='keyroom-source.zip', media_type='application/zip')


@app.get('/api/build')
def build_info():
    info = STATIC / 'build-info.json'
    if not info.is_file():
        raise HTTPException(503, 'Build metadata has not been generated.')
    return json.loads(info.read_text())
