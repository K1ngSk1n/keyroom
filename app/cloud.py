"""QR-only adapter. No CLI, password prompts, credential files, or debug logs."""
import json
import time
from urllib.parse import urlsplit, urljoin

import requests
from .upstream import XiaomiCloudConnector

REGIONS = ('cn', 'de', 'us', 'ru', 'tw', 'sg', 'in', 'i2')


def allowed_url(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ''
    return (parsed.scheme == 'https' and not parsed.username and not parsed.password
            and parsed.port in (None, 443)
            and (host == 'account.xiaomi.com' or host.endswith('.account.xiaomi.com')
                 or host == 'api.io.mi.com'
                 or host.endswith('.api.io.mi.com')))


class XiaomiSession(requests.Session):
    """Validate every request, including each server-directed redirect."""
    def __init__(self):
        super().__init__()
        self.trust_env = False

    def request(self, method, url, **kwargs):
        kwargs.setdefault('timeout', (5, 15))
        return super().request(method, url, **kwargs)

    def send(self, request, **kwargs):
        if not allowed_url(request.url):
            raise ValueError('Unexpected Xiaomi endpoint')
        return super().send(request, **kwargs)


class Cloud(XiaomiCloudConnector):
    def __init__(self):
        super().__init__()
        self._session.close()
        self._session = XiaomiSession()

    def login(self):
        raise NotImplementedError('Use the QR flow')

    def start(self):
        response = self._session.get('https://account.xiaomi.com/longPolling/loginUrl', params={
            '_qrsize': '320', 'qs': '%3Fsid%3Dxiaomiio%26_json%3Dtrue',
            'callback': 'https://sts.api.io.mi.com/sts', '_hasLogo': 'false',
            'sid': 'xiaomiio', 'serviceParam': '', '_locale': 'en_GB',
            '_dc': str(int(time.time() * 1000)),
        })
        response.raise_for_status()
        data = self.to_json(response.text)
        for key in ('qr', 'lp', 'loginUrl'):
            if not allowed_url(data[key]):
                raise ValueError('Unexpected Xiaomi endpoint')
        self.poll_url = data['lp']
        self.qr_deadline = time.monotonic() + min(float(data.get('timeout', 180)), 180)
        image = self._session.get(data['qr'])
        image.raise_for_status()
        kind = image.headers.get('Content-Type', '').split(';')[0]
        if kind not in ('image/png', 'image/jpeg') or len(image.content) > 1_000_000:
            raise ValueError('Unexpected QR image')
        return image.content, kind

    def wait(self, cancelled):
        while time.monotonic() < self.qr_deadline and not cancelled():
            try:
                response = self._session.get(self.poll_url, timeout=(5, 10))
            except requests.Timeout:
                continue
            response.raise_for_status()
            data = self.to_json(response.text)
            if not data.get('ssecurity') or not data.get('location'):
                raise ValueError('Xiaomi did not complete sign-in')
            self.userId = data['userId']
            self._ssecurity = data['ssecurity']
            result = self._session.get(data['location'])
            result.raise_for_status()
            # Cookie domains vary by Xiaomi endpoint/region.
            tokens = [c.value for c in self._session.cookies if c.name == 'serviceToken']
            if not tokens:
                raise ValueError('Missing Xiaomi session')
            self._serviceToken = tokens[-1]
            return True
        return False

    def devices(self, regions, cancelled):
        output, warnings = [], []
        for region in regions:
            if cancelled():
                return [], []
            try:
                homes = self.get_homes(region)
                counts = self.get_dev_cnt(region)
                if not homes or homes.get('code', 0) != 0:
                    warnings.append(region)
                    continue
                places = {(str(h['id']), str(self.userId)) for h in homes.get('result', {}).get('homelist', [])}
                for h in (counts or {}).get('result', {}).get('share', {}).get('share_family', []):
                    places.add((str(h['home_id']), str(h['home_owner'])))
                seen = set()
                for home, owner in sorted(places):
                    if cancelled():
                        return [], []
                    result = self.get_devices(region, home, owner)
                    if not result or result.get('code', 0) != 0:
                        warnings.append(region)
                        continue
                    for device in result.get('result', {}).get('device_info', []) or []:
                        if cancelled():
                            return [], []
                        did = str(device.get('did', ''))
                        if did in seen:
                            continue
                        seen.add(did)
                        key = ''
                        if did.startswith('blt.'):
                            try:
                                key = (self.get_beaconkey(region, did) or {}).get('result', {}).get('beaconkey', '')
                            except (requests.RequestException, ValueError, KeyError):
                                warnings.append(region)
                        output.append({
                            'name': str(device.get('name', 'Unnamed device')),
                            'id': did, 'model': str(device.get('model', '')),
                            'mac': str(device.get('mac', '')), 'region': region,
                            'token': str(device.get('token', '')), 'ble_key': key,
                        })
                        if len(output) >= 1000:
                            return output, sorted(set(warnings))
            except (requests.RequestException, ValueError, KeyError, TypeError):
                warnings.append(region)
        return output, sorted(set(warnings))

    def close(self):
        self._session.cookies.clear()
        self._session.close()
        self._serviceToken = self._ssecurity = self.userId = None
