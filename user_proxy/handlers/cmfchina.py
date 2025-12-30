# -*-coding:utf-8-*-
import logging
from urllib.parse import urljoin

import requests
from utensils.auth.token import encode_url

from user_proxy import config
from user_proxy.handlers.base import route, BaseHandler, permission_auth
from user_proxy.models.user import User


@route(r'/cmfchina/business-systems')
class BusinessSystemsHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def get(self, *args, **kwargs):
        target = config.get_config('unify_auth.auth_config.auth_scriber')
        target_url = urljoin(urljoin(target['internal_host'], target['subpath']), target['business_system_api'])
        page = max(int(self.get_argument("page", "1")), 1)
        size = int(self.get_argument("size", "20"))
        url = encode_url(f'{target_url}?page={page}&size={size}', target['app_id'], target['secret_key'], exclude_domain=True)
        data = []
        try:
            logging.info('get business_systems url: %s', url)
            res = requests.get(url, timeout=(3, 30), verify=False)
            if res.status_code == 200:
                logging.info('get business_systems success: %s', res.text)
            else:
                logging.error('get business_systems failed: %s, status_code: %s', res.text, res.status_code)
            data = res.json()['data']
        except Exception as e:
            logging.exception(e)
        return self.data(data)
