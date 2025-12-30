# -*-coding:utf-8-*-
# pylint:disable=too-many-locals,too-many-return-statements
import logging
from urllib.parse import urljoin

import requests

from user_proxy import config
from user_proxy.db import db_session, render_key
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.session import RedisDriver
from user_proxy.utils.cas import create_url


@route(r'/stocke/oauth-login')
class STOCKEOauthLoginHandler(BaseHandler):
    @staticmethod
    def get_access_token(corp_id):
        redis_driver = RedisDriver()
        if access_token := redis_driver.client.get(render_key('STOCKE_SSO_ACCESS_TOKEN')):
            logging.info('get access_token from cache')
            return True, access_token
        corp_secret = config.get_config('oauth2_auth.corp_secret')
        access_token_url = config.get_config('oauth2_auth.access_token_url')
        access_token_url = create_url(
            access_token_url,
            None,
            ('corpid', corp_id),
            ('corpsecret', corp_secret),
        )
        logging.info('get_access_token_url: %s', access_token_url)
        try:
            response = requests.get(access_token_url, verify=False)
            if response.status_code != 200:
                return False, f'get access_token error, status_code={response.status_code}'
            token_info = response.json()
            logging.info('access_token_info: %s', token_info)
            if token_info['errcode'] != 0:
                return False, f'get access_token error, {token_info}'
            if not token_info['access_token']:
                return False, 'empty access_token'
        except Exception as e:
            logging.exception(e)
            return False, 'permission denied'
        redis_driver.client.set(render_key('STOCKE_SSO_ACCESS_TOKEN'), token_info['access_token'], ex=token_info['expires_in'], nx=True)
        return True, token_info['access_token']

    def get(self, *args, **kwargs):
        code = self.get_argument('code', None)
        state = self.get_argument('state', None)

        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))
        origin_url = f'{trident_base}/api/v1/stocke/oauth-login'

        corp_id = config.get_config('oauth2_auth.corp_id')
        scope = config.get_config('oauth2_auth.scope')
        agent_id = config.get_config('oauth2_auth.agent_id')
        user_agent = self.request.headers.get("User-Agent")
        headers = {"User-Agent": user_agent}

        if code:
            user_info_url = config.get_config('oauth2_auth.user_info_url')
            flag, access_token = self.get_access_token(corp_id)
            if not flag:
                return self.error(access_token)

            user_info_url = create_url(
                user_info_url,
                None,
                ('access_token', access_token),
                ('code', code),
            )
            logging.info('get_user_info_url: %s', user_info_url)
            try:
                response = requests.get(user_info_url, headers=headers, verify=False)
                if response.status_code != 200:
                    return self.error(f'get user_info error, status_code={response.status_code}')
                user_info = response.json()
                logging.info('user_info: %s', user_info)
                if user_info['errcode'] != 0:
                    return self.error(f'user_info: {user_info}')
            except Exception as e:
                logging.exception(e)
                return self.error('permission denied')

            user = db_session.query(User).filter(User.ext_uname == user_info['UserId'], User.deleted == 0).first()
            if not user:
                return self.error('用户不存在')
            if user.user_data.get('work_status') == 2:
                return self.error('用户不具备访问权限')
            self.session['proxy_user_id'] = str(user.id)
            redirect_url = urljoin(trident_base, state) if state else trident_base
        else:
            authorize_url = config.get_config('oauth2_auth.authorize_url')
            url_args = [('appid', corp_id), ('redirect_uri', origin_url), ('response_type', 'code'), ('scope', scope), ('agentid', agent_id)]
            if state:
                url_args.append(('state', state))
            redirect_url = create_url(authorize_url, None, *url_args)
            redirect_url += '#wechat_redirect'
            logging.info('get_code_url: %s', redirect_url)
        return self.redirect(redirect_url)
