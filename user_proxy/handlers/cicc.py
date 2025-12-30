"""
中金单点登录api
"""
# pylint: disable=too-many-locals
import logging
import time
from urllib.parse import urljoin

import requests

from user_proxy import config
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.utils.cas import create_url


@route(r'/cicc/sso-login')
class CiccSSOLoginHandler(BaseHandler):
    """oauth2授权码模式"""

    @staticmethod
    def build_user_info(res_data):
        return {
            'uid': res_data['id'],  # 员工号
            'ext_uname': res_data['attributes']['workNo'],  # 员工号
            'username': res_data['attributes']['userName'],  # 中文名
            'account_no': res_data['attributes']['accountNo'],  # 账号
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
        origin_url = f'{trident_base}/api/v1/cicc/sso-login'

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
                redirect_url = create_url(trident_base, 'api/v1/cicc/sso-login', *url_args)
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


# @route(r'/cicc/sso-login-2')
# class CiccSSOLogin2Handler(BaseHandler):
#     def save_user(self, ext_uname):
#         user = db_session.query(User).filter(User.ext_uname == ext_uname).first()
#         if user:
#             return user
#         user = User.make_user(uid=ext_uname, ext_uname=ext_uname, username=ext_uname, _from='cicc')
#         return user
#
#     def get(self, *args, **kwargs):
#         origin = self.get_argument('origin')
#         auth_url = config.get_config('cicc_auth_2.auth_url')
#         token = self.get_argument('token')
#
#         try:
#             url = create_url(auth_url, None, ('token', token))
#             response = requests.get(url)
#             logging.info('auth response: %s', response.text)
#             data = response.json()
#             if data.get('code') == 500 or data.get('success') is False:
#                 logging.error('auth failed: %s', data['msg'])
#                 raise HTTPError(403)
#             user_data = data['data']
#         except Exception as e:
#             logging.exception(e)
#             raise HTTPError(403) from e
#
#         user = self.save_user(user_data['userAccount'])
#         if not user:
#             raise HTTPError(403)
#
#         subpath = config.get_config("webif.redirect_subpath", '')
#         trident_base = urljoin(self.origin_host, subpath.lstrip('/'))
#         redirect_url = urljoin(trident_base, origin)
#         self.session['proxy_user_id'] = str(user.id)
#         return self.redirect(redirect_url)
#
#
# @route(r'/cicc/user-login')
# class CiccUserLoginHandler(BaseHandler):
#     @staticmethod
#     def save_user(ext_uname):
#         user = db_session.query(User).filter(User.ext_uname == ext_uname).first()
#         if user:
#             return user
#         user = User.make_user(uid=ext_uname, ext_uname=ext_uname, username=ext_uname, _from='cicc')
#         return user
#
#     @staticmethod
#     def get_headers():
#         user_id = config.get_config('cicc_auth_3.user_id')
#         password = config.get_config('cicc_auth_3.password')
#         eid = config.get_config('cicc_auth_3.eid')
#         sys_id = config.get_config('cicc_auth_3.sys_id')
#
#         header_ns = ('auth', "http://esc.com//authentication")
#         xml_authentication_el = "auth:authentication"
#         el_user_id = Element('userID').setText(user_id)
#         el_password = Element('password').setText(password)
#         el_eid = Element('eid').setText(eid)
#         el_system_id = Element('systemID').setText(sys_id)
#         headers = Element(xml_authentication_el, ns=header_ns)
#         headers.append(el_system_id)
#         headers.append(el_user_id)
#         headers.append(el_password)
#         headers.append(el_eid)
#         return headers
#
#     def post(self, *args, **kwargs):
#         url = config.get_config('cicc_auth_3.auth_url')
#         app_code = config.get_config('cicc_auth_3.app_code')
#         body = self.get_json_body()
#         username = body.get('username')
#         password = body.get('password')
#         remote_ip = self.request.headers.get("X-Real-IP") or self.request.remote_ip
#         try:
#             client = get_suds_client(url)
#             headers = self.get_headers()
#             logging.info('soap_headers:%s', headers)
#             client.set_options(soapheaders=headers)
#             service = client.service
#             result = service.isAuthByPara(username, password, app_code, remote_ip)
#             # {
#             #     "retResult": {
#             #         "id": "lili",
#             #         "employeeNumber": "12312",
#             #         "attributes": [{"userName": ["lili"]}, {"language": ["zh"]}]
#             #     },
#             #     "retCode": "S"
#             # }
#             result = json.loads(result)
#             logging.info(result)
#             if result.get('retCode') == 'S':
#                 employee_number = result['retResult']['employeeNumber']
#                 res = service.getLDAPUserInfo(employee_number)
#                 # {
#                 #     "retResult": {
#                 #         "mail": "zhangsan@cicc.com",
#                 #         "LDAP_UID": "zhangsan"
#                 #     },
#                 #     "retCode": "S"
#                 # }
#                 res = json.loads(res)
#                 logging.info(res)
#                 if res.get('retCode') == 'S':
#                     ldap_uid = res['retResult']['LDAP_UID']
#                     # mail = res['retResult']['mail']
#                     user = self.save_user(ldap_uid)
#                 else:
#                     return self.error(message=res['retResult'], status_code=403)
#             else:
#                 return self.error(message=result['retResult'], status_code=403)
#         except Exception as e:
#             logging.exception(e)
#             return self.error('permission denied', status_code=403)
#         self.session['proxy_user_id'] = str(user.id)
#         return self.data(user.to_dict())
