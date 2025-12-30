# -*-coding:utf-8-*-
# pylint: disable=too-many-locals, too-many-return-statements, too-many-branches
import hashlib
import json
import logging
import time
from urllib.parse import urljoin, urlparse

import requests
from sqlalchemy.orm.attributes import flag_modified
from tornado.web import HTTPError

from user_proxy import config
from user_proxy.common.crypto_util import aes_ctr_decrypt
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url
from user_proxy.db import db_session
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.handlers.message import PERMISSION_DENIED
from user_proxy.models.user import User
from user_proxy.utils.cas import create_url
from user_proxy.utils.swhysc import generate_request_date, generate_signature


@route(r'/swhysc/sso-login')
class SWHYSCSSOLoginHandler(BaseHandler):
    def save_user(self, uid, ext_uname, username, customer_system):
        user = db_session.query(User).filter(User.ext_uname == ext_uname).first()
        if user:
            user.user_data.update({'customer_system': customer_system})
            flag_modified(user, 'user_data')
            db_session.commit()
            return user
        user = User.make_user(uid=uid, ext_uname=ext_uname, username=username, customer_system=customer_system, _from='swhysc')
        return user

    @staticmethod
    def verify_token(date, token, md5_str, system_id):
        data = {"date": date, "token": token, "systemId": system_id}
        mds_c = hashlib.md5(json.dumps(data, separators=(',', ':')).encode()).hexdigest()
        logging.info('regenerate md5: %s', mds_c)
        return md5_str == mds_c

    def get(self, *args, **kwargs):
        date_str = self.get_argument('date')
        md5_str = self.get_argument('md5')
        token = self.get_argument('token')
        customer_system = self.get_argument('customer_system', 'old_business_system')
        logging.info('sso login parameter: date: %s, token: %s, md5: %s, customer_system: %s', date_str, token, md5_str, customer_system)
        if customer_system not in ['old_business_system', 'new_business_system', 'portal_system']:
            return self.error('invalid customer_system')
        system_id = config.get_config(f'swhysc_auth.{customer_system}.system_id')
        if not self.verify_token(date_str, token, md5_str, str(system_id)):
            return self.error('verify token failed')
        aes_key = config.get_config(f'swhysc_auth.{customer_system}.aes_key')
        decrypt_token = aes_ctr_decrypt(token, aes_key, date_str)
        logging.info('decrypt_token: %s', decrypt_token)
        auth_url = config.get_config(f'swhysc_auth.{customer_system}.auth_url')
        try:
            if customer_system in ['new_business_system', 'portal_system']:
                logging.info('auth url: %s', auth_url)
                # 对接中台网关
                demeter_request_date = generate_request_date()
                demeter_auth_api = urlparse(auth_url).path
                sign_str = '\n'.join(["HmacSHA256", "POST", demeter_auth_api, "", demeter_request_date])
                demeter_signature = generate_signature(sign_str)
                logging.info('demeter_signature: %s', demeter_signature)
                headers = {
                    "accept": "*/*",
                    'Content-Type': 'application/json',
                    'X-DemeterRequestDate': demeter_request_date,
                    'X-DemeterSignature': demeter_signature,
                    'X-DemeterAccessKey': config.get_config('swhysc_auth.demeter_access_key'),
                    'X-Demeter-SystemId': str(config.get_config('swhysc_auth.demeter_system_id')),
                    'X-Demeter-Source': str(config.get_config('swhysc_auth.demeter_source')),
                    'X-Demeter-IP': self.request.headers.get("X-Forwarded-For")
                    if config.get_config('swhysc_auth.check_client_ip', True)
                    else config.get_config('swhysc_auth.demeter_ip'),
                }
                response = requests.post(auth_url, headers=headers, json={"token": decrypt_token}, verify=False)
            else:
                url = create_url(auth_url, None, ('token', decrypt_token))
                logging.info('auth url: %s', url)
                response = requests.post(url, verify=False)
            if response.status_code != 200:
                return self.error('get user_info error, status_code: %s', response.status_code)
            logging.info('auth response: %s', response.text)
            data = response.json()
            if (customer_system == 'old_business_system' and data.get('code') != 200) or (
                customer_system in ['new_business_system', 'portal_system'] and data.get('code') != "0"
            ):
                logging.error('auth failed: %s', data['msg'])
                raise HTTPError(403)
            if customer_system == 'old_business_system':
                ext_uname = data['data']['loginName']
                username = data['data']['userName']
            else:
                ext_uname = username = data['data']['loginName']
        except Exception as e:
            logging.exception(e)
            raise HTTPError(403) from e

        user = self.save_user(ext_uname, ext_uname, username, customer_system)
        if not user:
            raise HTTPError(403)

        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))
        self.session['proxy_user_id'] = str(user.id)

        # 新综业系统通过参数控制跳转链接地址
        redirect_type = self.get_argument('redirect_type', '')
        redirect_url_map = config.get_config('swhysc_redirect_url_config') or {}
        if customer_system == "new_business_system" and (redirect_url := redirect_url_map.get(redirect_type)):
            if redirect_type == "trident_user_manage":
                if not user.is_sys_admin and not user.is_swhysc_user_admin and not user.is_swhysc_sponsor_super_admin and not user.is_swhysc_bond_super_admin:
                    return self.error(PERMISSION_DENIED)
                return self.redirect(redirect_url + f'?session_id={self.session.session_id}')

            if redirect_type == "trident_role_manage":
                if not user.is_sys_admin and not user.is_swhysc_role_admin and not user.is_swhysc_sponsor_super_admin and not user.is_swhysc_bond_super_admin:
                    return self.error(PERMISSION_DENIED)
                return self.redirect(redirect_url + f'?session_id={self.session.session_id}')

            if redirect_type in ["autodoc_faulty_word", "autodoc_white_list", "autodoc_formula"]:
                if (
                    not any("admin" in (role.permission.get('autodoc_overall') or []) for role in user.roles)
                    and not user.is_swhysc_sponsor_super_admin
                    and not user.is_swhysc_bond_super_admin
                ):
                    return self.error(PERMISSION_DENIED)
            if (
                redirect_type == 'autodoc_dashboard'
                and not any(
                    item in (role.permission.get('autodoc_overall') or []) for role in user.roles for item in ['project_admin', 'sponsor_admin', 'bond_admin']
                )
                and not user.is_swhysc_sponsor_super_admin
                and not user.is_swhysc_bond_super_admin
            ):
                return self.error(PERMISSION_DENIED)
            url = get_off_redirect_url("autodoc_overall", user, origin_host=self.origin_host, origin=redirect_url, direct_jump="1")
            return self.redirect(url)

        return self.redirect(trident_base)


@route(r'/swhysc/oauth-login')
class SWHYSCOauthLoginHandler(BaseHandler):
    """oauth2授权码模式"""

    @staticmethod
    def build_user_info(res_data):
        return {
            'uid': res_data['id'],
            'ext_uname': res_data['attributes']['work_no'],  # 工号
            'username': res_data['attributes']['user_name'],  # 姓名
        }

    @staticmethod
    def oauth_timestamp():
        return int(round(time.time() * 1000))

    def get(self, *args, **kwargs):
        access_token = self.get_argument('access_token', None)
        code = self.get_argument('code', None)
        state = self.get_argument('state', None)

        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))
        origin_url = f'{trident_base}/api/v1/swhysc/oauth-login'

        oauth_base = config.get_config('oauth2_auth.base_url')
        client_id = config.get_config('oauth2_auth.client_id')
        user_agent = self.request.headers.get("User-Agent")
        headers = {"User-Agent": user_agent}
        logging.info('user_agent: %s', user_agent)

        if access_token:
            user_info_api = config.get_config('oauth2_auth.user_info_api')
            user_info_url = create_url(oauth_base, user_info_api, ('access_token', access_token))
            logging.info('user_info_url: %s', user_info_url)
            try:
                response = requests.get(user_info_url, headers=headers, verify=False)
                res_data = response.json()
                if response.status_code != 200:
                    return self.error(f'get user_info error, status_code={response.status_code}', status_code=400)
                user_info = self.build_user_info(res_data)
            except Exception as e:
                logging.exception(e)
                return self.error('permission denied')
            user = User.make_user(**user_info)
            if not user:
                return self.error('permission denied')
            self.session['proxy_user_id'] = str(user.id)
            redirect_url = urljoin(trident_base, state) if state else trident_base
        elif code:
            access_token_api = config.get_config('oauth2_auth.access_token_api')
            client_secret = config.get_config('oauth2_auth.client_secret')
            access_token_url = create_url(
                oauth_base,
                access_token_api,
                ('client_id', client_id),
                ('client_secret', client_secret),
                ('redirect_uri', origin_url),
                ('code', code),
                ('grant_type', 'authorization_code'),
                ('oauth_timestamp', self.oauth_timestamp()),
            )
            logging.info('get_access_token_url: %s', access_token_url)
            try:
                response = requests.post(access_token_url, headers=headers, verify=False)
                if response.status_code != 200:
                    return self.error(f'get access_token error, status_code={response.status_code}', status_code=400)
                access_token_info = response.json()
                logging.info('access_token_info: %s', access_token_info)
                url_args = [('access_token', access_token_info['access_token'])]
                if state:
                    url_args.append(('state', state))
                redirect_url = create_url(trident_base, 'api/v1/swhysc/oauth-login', *url_args)
                logging.info('redirect to %s', redirect_url)
            except Exception as e:
                logging.exception(e)
                return self.error('permission denied')
        else:
            authorize_api = config.get_config('oauth2_auth.authorize_api')
            url_args = [('client_id', client_id), ('redirect_uri', origin_url), ('response_type', 'code'), ('oauth_timestamp', self.oauth_timestamp())]
            if state:
                url_args.append(('state', state))
            redirect_url = create_url(oauth_base, authorize_api, *url_args)
            logging.info('get_code_url: %s', redirect_url)
        return self.redirect(redirect_url)
