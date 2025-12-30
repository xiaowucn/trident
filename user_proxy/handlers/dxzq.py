"""
东兴证券单点登录
"""

import logging
from urllib.parse import urljoin

import requests

from user_proxy import config
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.utils.cas import create_url


@route('/dxzq/sso-login')
class DxzqSSOLoginHandler(BaseHandler):
    @staticmethod
    def save_user(ext_uname):
        user = User.make_user(uid=ext_uname, ext_uname=ext_uname, username=ext_uname, _from='dxzq')
        return user

    def get(self, *args, **kwargs):
        origin = self.get_argument('origin', None)
        server = config.get_config('dxzq_auth.server')
        auth_uri = config.get_config('dxzq_auth.auth_uri')
        ticket = self.get_argument('ticket')

        auth_url = urljoin(server.rstrip('/'), auth_uri)
        logging.info('auth_url: %s, ticket: %s', auth_url, ticket)
        try:
            url = create_url(auth_url, None, ('ticket', ticket))
            response = requests.get(url, verify=False)
            if response.status_code != 200:
                logging.error('获取用户信息失败: http_code=%s', response.status_code)
                return self.error('获取用户信息失败', status_code=403)
            user_name = response.text
            logging.info('user_name: %s', user_name)
            if not user_name:
                return self.error('获取用户信息为空', status_code=403)
        except Exception as e:
            logging.exception(e)
            return self.error('permission denied', status_code=403)

        user = self.save_user(user_name)
        if not user:
            return self.error('permission denied', status_code=403)

        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))
        self.session['proxy_user_id'] = str(user.id)
        return self.redirect(origin) if origin else self.redirect(trident_base)
