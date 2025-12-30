import base64
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import requests

from user_proxy import config
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.web_services import ProxyWebService

ESB_USER = config.get_config("cgs_esb.user")
ESB_PASSWORD = config.get_config("cgs_esb.password")
ESB_URL = config.get_config("cgs_esb.url")
ESB_TUNNEL = config.get_config("cgs_esb.tunnel", "WCP")
ESB_SYS_CODE = config.get_config("cgs_esb.sys_code", "SDA")
ESB_TIMEOUT = config.get_config("cgs_esb.time_out", 300)
ESB_DEFAULT_FUNC_VERSION = config.get_config("cgs_esb.default_func_version", "1")


@dataclass
class ESBConfig:
    user: str
    password: str
    url: str
    sys_code: str
    default_function_version: str
    timeout: int


@dataclass
class ESBRequest:
    function_no: str
    headers: dict[str, str] = field(default_factory=dict)
    query_params: None | dict[str, str] = None
    request_body: None | dict[str, Any] = None
    function_version: None | str = None


class ESBService:
    def __init__(self):
        self.config = ESBConfig(
            user=ESB_USER,
            password=ESB_PASSWORD,
            url=ESB_URL,
            sys_code=ESB_SYS_CODE,
            default_function_version=ESB_DEFAULT_FUNC_VERSION,
            timeout=ESB_TIMEOUT,
        )

    @staticmethod
    def _generate_nonce() -> str:
        return base64.b64encode(os.urandom(16)).decode("utf-8")

    @staticmethod
    def _generate_timestamp() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def _md5_encryption(data: str) -> str:
        return hashlib.md5(data.encode("utf-8")).hexdigest()

    def _generate_digest(self, nonce: str, created: str) -> str:
        sha1 = hashlib.sha1()
        sha1.update(base64.b64decode(nonce))
        sha1.update(created.encode("utf-8"))
        sha1.update(self.config.password.encode("utf-8"))
        return base64.b64encode(sha1.digest()).decode("utf-8")

    def _build_headers(self, req: ESBRequest):
        nonce = self._generate_nonce()
        created = self._generate_timestamp()
        digest = self._generate_digest(nonce, created)
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Tracking-Id": str(uuid.uuid4()),
            "User": self.config.user,
            "Created": created,
            "Nonce": nonce,
            "Password-Digest": digest,
            "Function-No": req.function_no,
            "Function-Version": req.function_version or self.config.default_function_version,
            "Caller-System-Code": self.config.sys_code,
        }
        headers.update(req.headers)
        req.headers = headers
        return req

    def call(self, function_no, payload: dict):
        req = ESBRequest(
            function_no=function_no,
            request_body=payload,
        )
        self._build_headers(req)
        return requests.post(
            self.config.url,
            headers=req.headers,
            params=req.query_params,
            json=req.request_body,
            timeout=self.config.timeout,
        )


def check_csg_token(token: str):
    response = ESBService().call(config.get_config("cgs_esb.check_func"), {"tunnel": ESB_TUNNEL, "target": ESB_SYS_CODE, "token": token, "weekendPass": "1"})
    if not response.ok:
        return None
    info = response.json()["data"]["passwd"]
    return json.loads(info)


@route(r'/cgs/token-login')
class CGSTokenHandler(BaseHandler):
    def get(self):
        token = self.get_argument('token', None)
        if not token:
            return self.error('invalid params')
        try:
            user_info = check_csg_token(token)
            if not user_info:
                return self.error('无效的 token')
            uid = user_info["user"]
            name = user_info.get("name", uid)
        except Exception:
            return self.error("未获取到用户信息，请联系管理员")

        user = User.make_user(uid=uid, ext_uname=uid, username=name)
        self.session['proxy_user_id'] = str(user.id)
        if app := self.get_argument('app', "chatdoc"):
            args = {key: self.get_argument(key, None) for key in self.request.arguments.keys()}
            args.update({'sys': app})
            res = ProxyWebService.get_off(current_user_id=self.current_user.id, origin_host=self.origin_host, arguments=args, user_id=user.id)
            return self.hand_out_data(res)

        redirect_url = self.gen_redirect_url(config.get_config('cas_auth.cas_after_login'))
        logging.debug('Redirecting to: %s', redirect_url)
        return self.redirect(redirect_url)
