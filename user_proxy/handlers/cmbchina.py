# -*-coding:utf-8-*-
# pylint: disable=too-many-locals,anomalous-backslash-in-string,too-many-return-statements
import base64
import json
import logging
import time
import urllib.parse
import uuid
from urllib.parse import urljoin

import requests
from sqlalchemy import true
from utensils.util import generate_timestamp

from user_proxy import config
from user_proxy.common.crypto_util import aes_decrypt, aes_encrypt
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url, get_user_sys_permission
from user_proxy.db import db_session
from user_proxy.handlers.base import route, BaseHandler, permission_auth
from user_proxy.models.cmbchina import BusinessSystem
from user_proxy.models.user import User, Role
from user_proxy.utils.cas import create_url
from user_proxy.utils.cmbchina import CMBSM2SignWithSM3


@route(r'/business-systems')
class BusinessSystemsHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def get(self, *args, **kwargs):
        name = self.get_argument('name', '')
        cond = true()
        orderby = []
        if name:
            cond &= BusinessSystem.name.like("%{}%".format(name.replace('%', '\%')))
            orderby.append(BusinessSystem.name)
        orderby.append(BusinessSystem.id.desc())
        business_systems = db_session.query(BusinessSystem).filter(cond).order_by(*orderby).all()
        return self.data({"total": len(business_systems), "items": [item.to_dict() for item in business_systems]})


@route(r'/business-system/roles')
class BusinessSystemRolesHandler(BaseHandler):
    @staticmethod
    def transfer_permission(permission):
        config_sys = config.get_config('front_config.sub_sys_config')
        valid_sys_map = {sub_sys: value['title'] for sub_sys, value in config_sys.items() if value['open']}
        config_permission = config.get_config('unify_auth.permission')
        valid_permission = {}
        for sub_sys, sub_sys_permissions in permission.items():
            if sub_sys not in valid_sys_map:
                continue
            config_sub_sys_permissions = config_permission.get(sub_sys)
            if not config_sub_sys_permissions:
                continue
            permissions = [f'{sub_sys}-{config_sub_sys_permissions[item]}' for item in sorted(sub_sys_permissions) if item in config_sub_sys_permissions]
            if not permissions:
                continue
            valid_permission[valid_sys_map[sub_sys]] = permissions
        return valid_permission

    @staticmethod
    def generate_role_id_token(role_id):
        secret_key = config.get_config('oauth2_auth.role_id_secret_key')
        return base64.urlsafe_b64encode(aes_encrypt(f'{role_id}-{uuid.uuid4().hex[6:10]}'.encode(), secret_key, fill=True)).decode()

    def get(self, *args, **kwargs):
        code = self.get_argument('business_system_code', '')
        roles = db_session.query(Role).filter(Role.role_data.op('->>')('business_system_code') == code).order_by(Role.id).all()
        items = [
            {
                'role_id': item.id,
                'role_name': item.name,
                'permission': self.transfer_permission(item.permission or {}),
                'role_id_token': self.generate_role_id_token(item.id),
            }
            for item in roles
        ]

        return self.data({"total": len(roles), "items": items})


@route(r'/cmbchina/sso-login')
class CMBCHINASsoLoginHandler(BaseHandler):
    @staticmethod
    def generate_headers(client_id, code):
        sign_api_private_key = config.get_config('oauth2_auth.sign_api_private_key')
        sign_api_public_key = config.get_config('oauth2_auth.sign_api_public_key')
        nonce = str(uuid.uuid4()).replace("-", "")
        timestamp = str(int(time.time() * 1000))
        code_sign = (
            'POST\n'
            + 'Accept:*/*\n'
            + 'Content-Type:application/json\n'
            + 'X-ClientId:'
            + client_id
            + '\n'
            + 'X-Nonce:'
            + nonce
            + '\n'
            + 'X-Timestamp:'
            + timestamp
            + '\n'
            + '\n'
            + 'client_id='
            + client_id
            + '&code='
            + code
            + '&grant_type=authorization_code'
        )
        logging.info('header code_sign: %s', code_sign)
        api_sign = CMBSM2SignWithSM3(sign_api_private_key, sign_api_public_key).sm2_sign_with_sm3(code_sign)
        logging.info('header api sign: %s', api_sign)
        headers = {
            'Accept': '*/*',
            'Content-Type': 'application/json',
            'X-Timestamp': timestamp,
            'X-ClientId': client_id,
            'X-Nonce': nonce,
            'X-Signature': api_sign,
            'X-Signature-Headers': 'Accept,Content-Type,X-ClientId,X-Nonce,X-Timestamp',
        }
        return headers

    @staticmethod
    def get_user_info(id_token):
        user_data = CMBSM2SignWithSM3.decode_jwt_token(id_token)
        logging.info('user_data: %s', user_data)
        return {"uid": user_data['ystId'], "ext_uname": user_data['employeeId'], "username": user_data['userName']}

    def get(self, *args, **kwargs):
        code = self.get_argument('code', None)
        sys = self.get_argument('sys', None)
        role_id_token = self.get_argument('role_id_token', '')

        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))

        oauth_base = config.get_config('oauth2_auth.base_url')
        client_id = config.get_config('oauth2_auth.client_id')

        if code:
            access_token_server = config.get_config('oauth2_auth.access_token_server')
            access_token_api = config.get_config('oauth2_auth.access_token_api')
            access_token_url = create_url(
                access_token_server,
                access_token_api,
                ('client_id', client_id),
                ('code', code),
                ('grant_type', 'authorization_code'),
            )
            logging.info('get_access_token_url: %s', access_token_url)
            headers = self.generate_headers(client_id, code)
            logging.info('headers: %s', headers)
            try:
                response = requests.post(access_token_url, headers=headers, verify=False, timeout=5)
                if response.status_code != 200:
                    logging.error('request access_token error, response: %s', response.text)
                    return self.error(f'get access_token error, status_code={response.status_code}', status_code=400)
                access_token_info = response.json()
                logging.info('access_token_info: %s', access_token_info)
                id_token = access_token_info['id_token']
                public_key = config.get_config('oauth2_auth.public_key')
                flag, message = CMBSM2SignWithSM3('', public_key).verify(id_token, client_id)
                if not flag:
                    return self.error('id_token验证失败: %s', message)
                user_info = self.get_user_info(id_token)
                # 单点用户首次登录，以携带的 role_id_token 为默认值；被创建后，该用户的角色权限，以 其在文档中台被赋予的为准 （单点中带有的 role_id_token会被抛弃），删除用户当新增用户处理
                db_user = db_session.query(User).filter(User.ext_uname == user_info['ext_uname'], User.deleted == 0).first()
                if not db_user:
                    if not role_id_token:
                        return self.error('您不具备系统访问权限')
                    secret_key = config.get_config('oauth2_auth.role_id_secret_key')
                    user_info['role_id'] = int(aes_decrypt(base64.urlsafe_b64decode(role_id_token.encode()), secret_key, strip=True).decode().split('-')[0])
                user = User.make_user(**user_info)
                if not user:
                    return self.error('permission denied')
                self.session['proxy_user_id'] = str(user.id)

                if sys and not get_user_sys_permission(user, sys):
                    return self.error('您不具备该子系统访问权限')
                redirect_url = get_off_redirect_url(sys, user, origin_host=self.origin_host) if sys else trident_base
                logging.info('redirect to %s', redirect_url)
            except Exception as e:
                logging.exception(e)
                return self.error('permission denied')
        else:
            origin_url = f'{trident_base}/api/v1/cmbchina/sso-login'
            trident_args = []
            if sys:
                trident_args.append(('sys', sys))
            if role_id_token:
                trident_args.append(('role_id_token', role_id_token))
            origin_url = create_url(origin_url, None, *trident_args)

            authorize_api = config.get_config('oauth2_auth.authorize_api')
            url_args = [('client_id', client_id), ('redirect_uri', origin_url), ('response_type', 'code')]
            redirect_url = create_url(oauth_base, authorize_api, *url_args)
            logging.info('get_code_url: %s', redirect_url)
        return self.redirect(redirect_url)


@route(r"/auth-server/token")
class MockedAuthToken(BaseHandler):
    code_user_map = {
        "dsp1": {"ystId": "dtest1", "employeeId": "1992112000", "userName": "dsp-转让"},
        "elaine": {"ystId": "GA001", "employeeId": "GA001", "userName": "elaine"},
        "elaine2": {"ystId": "SC001", "employeeId": "SC001", "userName": "elaine2"},
        "elaine3": {"ystId": "SA001", "employeeId": "SA001", "userName": "elaine3"},
        'glazer_1': {"ystId": "83001", "employeeId": "1000001", "userName": "glazer_1"},
        'glazer_2': {"ystId": "83002", "employeeId": "1000002", "userName": "glazer_2"},
        'glazer_1_2': {"ystId": "83003", "employeeId": "1000003", "userName": "glazer_1_2"},
        'scriber_audit': {"ystId": "83004", "employeeId": "1000004", "userName": "scriber_audit"},
        'scriber_all': {"ystId": "83005", "employeeId": "1000005", "userName": "scriber_all"},
        'all1': {"ystId": "83006", "employeeId": "1000006", "userName": "all1"},
        'all2': {"ystId": "83007", "employeeId": "1000007", "userName": "all2"},
        'USY1024': {"ystId": "8310241", "employeeId": "1000241", "userName": "USY1024"},
        'USC1024': {"ystId": "8310241", "employeeId": "1000242", "userName": "USC1024"},
        'lixiaolong10002': {"ystId": "lixiaolong10002", "employeeId": "lixiaolong10002", "userName": "lixiaolong10002"},
        'liwenting': {"ystId": "liwenting", "employeeId": "liwenting", "userName": "liwenting"},
        'liwenting01': {"ystId": "liwenting01", "employeeId": "liwenting01", "userName": "liwenting01"},
        'liwenting02': {"ystId": "liwenting02", "employeeId": "liwenting02", "userName": "liwenting02"},
        'liwenting03': {"ystId": "liwenting03", "employeeId": "liwenting03", "userName": "liwenting03"},
        'liwenting04': {"ystId": "liwenting04", "employeeId": "liwenting04", "userName": "liwenting04"},
        'sso_1': {"ystId": "99838401", "employeeId": "sso_1", "userName": "sso_1"},
        'sso_2': {"ystId": "99838402", "employeeId": "sso_2", "userName": "sso_2"},
        'sso_3': {"ystId": "99838403", "employeeId": "sso_3", "userName": "sso_3"},
        'sso_4': {"ystId": "99838404", "employeeId": "sso_4", "userName": "sso_4"},
    }

    def check_signare(self):
        public_key = config.get_config('oauth2_auth.sign_api_public_key')

        headers = self.request.headers
        msg = ["POST"]
        for item in headers['X-Signature-Headers'].split(','):
            msg.append(f"{item}:{headers[item]}")
        msg.append('')
        msg.append(self.request.full_url().split('?')[1])
        cmb_decrypt_signer = CMBSM2SignWithSM3('', public_key)
        logging.info('\n'.join(msg))
        return cmb_decrypt_signer.sm2_verify_with_sm3(headers['X-Signature'], '\n'.join(msg))

    def post(self):
        client_id = self.get_argument('client_id')
        code = self.get_argument('code')
        grant_type = self.get_argument('grant_type')
        assert client_id == 'a806eec13b3f4dc0ab6fdb98fda7b2fc'
        assert grant_type == 'authorization_code'
        if not self.check_signare():
            logging.error('验签失败')
            return self.error('验签失败')

        _jwt_token = 'eyJraWQiOiJTTTNXaXRoU00yIiwidHlwIjoiSldUIiwiYWxnIjoiU00zV2l0aFNNMiJ9.eyJqb2luZWRFbnRlcnByaXNlSWRzIjoidWF0ZjA0YTY3MDU4ODJhYzAxNzA1ODhmMGQ4NzAwMGMiLCJwYXRoTmFtZSI6IuaLm-WVhumTtuihjC_mgLvooYwv5L-h5oGv5oqA5pyv6YOoL-aVsOaNrui1hOS6p-S4juW5s-WPsOeglOWPkeS4reW_gy_kurrlt6Xmmbrog73lrp7pqozlrqQv6K6k55-l6K6h566X5LqM5a6kKOaIkOmDvSkiLCJzdWIiOiJCNUEzNkExRjM4OEQ5MEU0RkJDRkVCRTdCOEMyOUM2MCIsIm9wZW5JZCI6IkI1QTM2QTFGMzg4RDkwRTRGQkNGRUJFN0I4QzI5QzYwIiwib3JpZ2luUGF0aElkIjoiMTAwMDAxLzEwMDAwMy85OTAwMDEvOTkxMTY3Lzk5MDc2Ni85OTE2MTgiLCJkZWZhdWx0RW50ZXJwcmlzZUlkIjoidWF0ZjA0YTY3MDU4ODJhYzAxNzA1ODhmMGQ4NzAwMGMiLCJpc3MiOiJvYS1hdXRoLnBhYXMuY21iY2hpbmEuY29tIiwieXN0SWQiOiIyNzM2OTUiLCJwYXRoSWQiOiIyYzllYmZiMTcxYzNmYzdiMDE3MWM0ZGNmYjljNGFiMi8yYzllYmZiMTcxYzNmYzdiMDE3MWM0ZGNmYmZlNGFiNS8yYzllYmZiMTcxYzNmYzdiMDE3MWM0YzZjYjRlMTA2Ni8yYzllYmZiMTcxYzNmYzdiMDE3MWM0YzZjZmU2MTA3Yi8yYzllYmZiMTcxYzNmYzdiMDE3MWM0Yzc3ZjlhMTQxNS8yYzlmZDVhZTc2ZjY1OWUzMDE3NzIyYWJjNWMxNWI4MiIsIm9yZ0lkIjoiMmM5ZmQ1YWU3NmY2NTllMzAxNzcyMmFiYzVjMTViODIiLCJleHAiOjE3MjE2Mzg5NjcsImlhdCI6MTcyMTYyODE2NywiZW50ZXJwcmlzZU5hbWUiOiLmi5vllYbpk7booYwiLCJzYXBJZCI6IjgwMjczNjk1Iiwib3JnTmFtZSI6IuiupOefpeiuoeeul-S6jOWupCjmiJDpg70pIiwib3JpZ2luT3JnSWQiOiI5OTE2MTgiLCJwYXNzZWRBdXRoVHlwZXMiOiJ7XCJ2ZXJpZnlDb2RlXCI6MTcyMTYxNzI4NjgyOX0iLCJuZXRFbnYiOjAsImVtcGxveWVlSWQiOiI4MDI3MzY5NSIsInVzZXJOYW1lIjoi5pyx55Ge5bOwIiwiYXVkIjoie1wiaWRcIjpcImE4MDZlZWMxM2IzZjRkYzBhYjZmZGI5OGZkYTdiMmZjXCIsXCJuYW1lXCI6XCJMTE1fc3RcIixcIm51bWJlclwiOlwiQUEwMS4wMVwiLFwicHVibGljS2V5XCI6XCJCUFQrVEluUmMzaTBBazNRWDYrdU53WmUrTWl6Y1JGSzJLRS9zbjMvUlpyMEM2TDBwbGlVU1haenlzZC9kOHNYdWgvMHdtT1VXekdoZ3VVOUhRTDF1VGM9XCJ9IiwicGxhdGZvcm1Vc2VyVHlwZSI6IjEiLCJjbGllbnRJcCI6Ijk5LjE3LjIwOS40MCIsImVudGVycHJpc2VJZCI6InVhdGYwNGE2NzA1ODgyYWMwMTcwNTg4ZjBkODcwMDBjIiwidXNlclR5cGUiOiIyIn0.j3gqoPuT35G9pxSvG0YKAfITe0gaF3pu7kHhwBL9IkKAxpNcKHG7iFkokkNodFgqTTjcBI-jEus1nduImZ_Cpw'
        # 生成测试用户jwt_token
        user_data = CMBSM2SignWithSM3.decode_jwt_token(_jwt_token)
        user_data.update({"exp": generate_timestamp() + 360 * 60 * 60 * 24, **self.code_user_map[code]})
        client_private_key = "Ev6dYQrht/YP6CFNb/rEbEK97uQRTI31Lrx5kO7OkqM="
        client_public_key = "BOKvpipe6aM7xn9sh7V3Y3+lYCl20cEwYiihj3d/hkORpyvTC90pMtVfScR0oSpLU2PqctSOvjsFzVpF0JePtGE="
        cmb_encrypt_signer = CMBSM2SignWithSM3(client_private_key, client_public_key)
        header_payload = 'eyJraWQiOiJTTTNXaXRoU00yIiwidHlwIjoiSldUIiwiYWxnIjoiU00zV2l0aFNNMiJ9'
        json_payload = base64.urlsafe_b64encode(json.dumps(user_data, separators=(",", ":")).encode("utf-8")).decode()
        sign = cmb_encrypt_signer.sm2_sign_with_sm3(f'{header_payload}.{json_payload}')
        id_token = f'{header_payload}.{json_payload}.{sign}'
        flag, comment = cmb_encrypt_signer.verify(id_token, client_id)
        if not flag:
            return self.error(comment)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json.dumps({"id_token": id_token}, ensure_ascii=False))


@route(r"/auth-server/auth")
class MockedAuthServer(BaseHandler):
    def get(self, *args):
        redirect_url = self.get_argument('redirect_uri')
        main_url, query = urllib.parse.splitquery(redirect_url)
        redirect_url += '?code=lixiaolong10002' if not query else '&code=lixiaolong10002'
        return self.redirect(redirect_url)
