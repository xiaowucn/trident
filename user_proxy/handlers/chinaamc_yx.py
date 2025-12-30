# -*-coding:utf-8-*-
import base64
import hashlib
import json
import logging
from urllib.parse import urljoin

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from tornado.web import HTTPError

from user_proxy import config
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.utils.authtoken import generate_timestamp


@route(r'/chinaamc/sso-login')
class CHINAAMCSSOLoginHandler(BaseHandler):
    @staticmethod
    def verify_sign(usertoken, nonce, timestamp, sign):
        sign_expired = config.get_config('chinaamc_auth.sign_expired')
        current_time = generate_timestamp() * 1000
        if sign_expired and int(timestamp) + int(sign_expired) < current_time:
            logging.info('sign expired: timestamp: %s, sign_expired: %s, current_time: %s', timestamp, sign_expired, current_time)
            return False
        params = {"usertoken": usertoken, "nonce": nonce, "timestamp": timestamp}
        # 对参数按键名进行升序排序
        sorted_params = sorted(params.items(), key=lambda x: x[0])
        # 生成待签名字符串
        sign_str = '&'.join([f"{key}={json.dumps(value) if not isinstance(value, str) else value}" for key, value in sorted_params if value is not None])
        # 计算MD5签名并返回
        generate_sign = hashlib.md5(sign_str.encode()).hexdigest()
        logging.info('generate sign: %s', generate_sign)
        return generate_sign == sign

    @staticmethod
    def aes_decrypt_token(token):
        key = config.get_config('chinaamc_auth.aes_key')
        iv = config.get_config('chinaamc_auth.aes_iv')

        aes = AES.new(key.encode(), AES.MODE_CBC, iv.encode())
        byte_str = token.encode()
        b64_str = base64.b64decode(byte_str)
        decrypted_data = aes.decrypt(b64_str)
        un_padded_data = unpad(decrypted_data, AES.block_size)
        return json.loads(un_padded_data.decode())

    def get(self, *args, **kwargs):
        # 单点认证参数
        usertoken = self.get_argument('usertoken')
        nonce = self.get_argument('nonce')
        timestamp = self.get_argument('timestamp')
        sign = self.get_argument('sign')

        # 子系统参数
        sys = self.get_argument('sys', '')
        origin = self.get_argument('origin', '')

        if not self.verify_sign(usertoken, nonce, timestamp, sign):
            return self.error('verify sign error')

        user_data = self.aes_decrypt_token(usertoken)
        user = User.make_user(user_data['id'], user_data['id'], username=user_data['name'])
        if not user:
            raise HTTPError(403)

        self.session['proxy_user_id'] = str(user.id)

        subpath = config.get_config("webif.redirect_subpath", '')
        url = urljoin(self.origin_host, subpath.lstrip('/'))
        if sys:
            url = get_off_redirect_url(sys, user, origin_host=self.origin_host, origin=origin)
            if not url:
                return self.error('sys: {} not config'.format(sys))
        return self.redirect(url)
