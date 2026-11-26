# Adapted from Xiaomi-cloud-tokens-extractor by Piotr Machowski (MIT).
# See THIRD_PARTY_LICENSE and UPSTREAM.md.
from abc import ABC, abstractmethod
import base64
import hashlib
import hmac
import json
import os
import random
import time
import requests
from Crypto.Cipher import ARC4

class XiaomiCloudConnector(ABC):

    def __init__(self):
        self._agent = self.generate_agent()
        self._device_id = self.generate_device_id()
        self._session = requests.session()
        self._ssecurity = None
        self.userId = None
        self._serviceToken = None

    @abstractmethod
    def login(self) -> bool:
        pass

    def get_homes(self, country):
        url = self.get_api_url(country) + "/v2/homeroom/gethome"
        params = {
            "data": '{"fg": true, "fetch_share": true, "fetch_share_dev": true, "limit": 300, "app_ver": 7}'}
        return self.execute_api_call_encrypted(url, params)

    def get_devices(self, country, home_id, owner_id):
        url = self.get_api_url(country) + "/v2/home/home_device_list"
        params = {
            "data": '{"home_owner": ' + str(owner_id) +
            ',"home_id": ' + str(home_id) +
            ',  "limit": 200,  "get_split_device": true, "support_smart_home": true}'
        }
        return self.execute_api_call_encrypted(url, params)

    def get_dev_cnt(self, country):
        url = self.get_api_url(country) + "/v2/user/get_device_cnt"
        params = {
            "data": '{ "fetch_own": true, "fetch_share": true}'
        }
        return self.execute_api_call_encrypted(url, params)

    def get_beaconkey(self, country, did):
        url = self.get_api_url(country) + "/v2/device/blt_get_beaconkey"
        params = {
            "data": '{"did":"' + did + '","pdid":1}'
        }
        return self.execute_api_call_encrypted(url, params)

    def execute_api_call_encrypted(self, url, params):
        headers = {
            "Accept-Encoding": "identity",
            "User-Agent": self._agent,
            "Content-Type": "application/x-www-form-urlencoded",
            "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2",
            "MIOT-ENCRYPT-ALGORITHM": "ENCRYPT-RC4",
        }
        cookies = {
            "userId": str(self.userId),
            "yetAnotherServiceToken": str(self._serviceToken),
            "serviceToken": str(self._serviceToken),
            "locale": "en_GB",
            "timezone": "GMT+02:00",
            "is_daylight": "1",
            "dst_offset": "3600000",
            "channel": "MI_APP_STORE"
        }
        millis = round(time.time() * 1000)
        nonce = self.generate_nonce(millis)
        signed_nonce = self.signed_nonce(nonce)
        fields = self.generate_enc_params(url, "POST", signed_nonce, nonce, params, self._ssecurity)
        response = self._session.post(url, headers=headers, cookies=cookies, params=fields)
        if response.status_code == 200:
            decoded = self.decrypt_rc4(self.signed_nonce(fields["_nonce"]), response.text)
            return json.loads(decoded)
        return None

    @staticmethod
    def get_api_url(country):
        return "https://" + ("" if country == "cn" else (country + ".")) + "api.io.mi.com/app"

    def signed_nonce(self, nonce):
        hash_object = hashlib.sha256(base64.b64decode(self._ssecurity) + base64.b64decode(nonce))
        return base64.b64encode(hash_object.digest()).decode("utf-8")

    @staticmethod
    def signed_nonce_sec(nonce, ssecurity):
        hash_object = hashlib.sha256(base64.b64decode(ssecurity) + base64.b64decode(nonce))
        return base64.b64encode(hash_object.digest()).decode("utf-8")

    @staticmethod
    def generate_nonce(millis):
        nonce_bytes = os.urandom(8) + (int(millis / 60000)).to_bytes(4, byteorder="big")
        return base64.b64encode(nonce_bytes).decode()

    @staticmethod
    def generate_agent():
        agent_id = "".join(
            map(lambda i: chr(i), [random.randint(65, 69) for _ in range(13)])
        )
        random_text = "".join(map(lambda i: chr(i), [random.randint(97, 122) for _ in range(18)]))
        return f"{random_text}-{agent_id} APP/com.xiaomi.mihome APPV/10.5.201"

    @staticmethod
    def generate_device_id():
        return "".join(map(lambda i: chr(i), [random.randint(97, 122) for _ in range(6)]))

    @staticmethod
    def generate_signature(url, signed_nonce, nonce, params):
        signature_params = [url.split("com")[1], signed_nonce, nonce]
        for k, v in params.items():
            signature_params.append(f"{k}={v}")
        signature_string = "&".join(signature_params)
        signature = hmac.new(base64.b64decode(signed_nonce), msg=signature_string.encode(), digestmod=hashlib.sha256)
        return base64.b64encode(signature.digest()).decode()

    @staticmethod
    def generate_enc_signature(url, method, signed_nonce, params):
        signature_params = [str(method).upper(), url.split("com")[1].replace("/app/", "/")]
        for k, v in params.items():
            signature_params.append(f"{k}={v}")
        signature_params.append(signed_nonce)
        signature_string = "&".join(signature_params)
        return base64.b64encode(hashlib.sha1(signature_string.encode("utf-8")).digest()).decode()

    @staticmethod
    def generate_enc_params(url, method, signed_nonce, nonce, params, ssecurity):
        params["rc4_hash__"] = XiaomiCloudConnector.generate_enc_signature(url, method, signed_nonce, params)
        for k, v in params.items():
            params[k] = XiaomiCloudConnector.encrypt_rc4(signed_nonce, v)
        params.update({
            "signature": XiaomiCloudConnector.generate_enc_signature(url, method, signed_nonce, params),
            "ssecurity": ssecurity,
            "_nonce": nonce,
        })
        return params

    @staticmethod
    def to_json(response_text):
        return json.loads(response_text.replace("&&&START&&&", ""))

    @staticmethod
    def encrypt_rc4(password, payload):
        r = ARC4.new(base64.b64decode(password))
        r.encrypt(bytes(1024))
        return base64.b64encode(r.encrypt(payload.encode())).decode()

    @staticmethod
    def decrypt_rc4(password, payload):
        r = ARC4.new(base64.b64decode(password))
        r.encrypt(bytes(1024))
        return r.encrypt(base64.b64decode(payload))
