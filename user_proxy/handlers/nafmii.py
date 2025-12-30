# -*-coding:utf-8-*-
import hashlib
import logging
from urllib.parse import urljoin

import requests

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.handlers.message import (
    INVALID_PARAMETERS,
)
from user_proxy.handlers.proxy import LoginHandler
from user_proxy.models.user import User, Role


@route(r'/personal/login')
class PersonalLoginHandler(LoginHandler):

    def get_client_ip(self):
        remote_ip = self.request.headers.get("X-Forwarded-For") or ''
        return remote_ip.split(',')[0]

    @staticmethod
    def check_password(username, password):
        base_server = config.get_config('sso_auth.base_server')
        personal_login_api = config.get_config('sso_auth.personal_login_api')
        personal_login_url = urljoin(base_server, personal_login_api)
        logging.info('personal login url %s', personal_login_url)
        json_data = {
            "account": username,
            "password": hashlib.md5(password.encode()).hexdigest(),
        }
        logging.debug('personal login json_data %s', json_data)
        try:
            res = requests.post(personal_login_url, json=json_data, timeout=5, verify=False)
            if res.status_code != 200:
                logging.error('personal login request text: %s', res.text)
                return False, f'personal login request failed, status code: {res.status_code}'
            res_data = res.json()
            if str(res_data['data']['resultCode']) != '0':
                logging.error('personal login response data: %s', res_data)
                return False, f"personal login response data, resultCode: {res_data['data']['resultCode']}, msg: {res_data['data']['resultMsg']}"

            personal_biz_code = config.get_config('sso_auth.personal_biz_code')
            system_data = [item for item in res_data['data']['systemList'] if str(item['bizCode']) == str(personal_biz_code)]
            if not system_data:
                logging.info('personal login response systemList data: %s', res_data['data']['systemList'])
                return False, f'not found valid system data, config personal_biz_code: {personal_biz_code}'

            data = {
                'uid': system_data[0]['accountList'][0]['accountId'],
                'ext_uname': system_data[0]['accountList'][0]['accountId'],
                'username': system_data[0]['accountList'][0]['accountName'],
            }
        except Exception as e:
            logging.error(e)
            return False, 'check personal login exception'
        return True, data

    def post(self, *args, **kwargs):
        body = self.get_json_body()
        username = body.get('username')
        password = body.get('password')
        if not username or not password:
            return self.error(INVALID_PARAMETERS)

        flag, msg = self.check_captcha()
        if not flag:
            return self.error(msg)

        flag, data = self.check_password(username, password)
        if not flag:
            return self.error(data)
        role = db_session.query(Role).filter(Role.name == 'biz_role').first()
        user = User.make_user(uid=data['uid'], ext_uname=data['ext_uname'], username=data['username'], login_method='personal', _from='nafmii', role_id=role.id)
        self.session['proxy_user_id'] = str(user.id)
        return self.data(user.to_dict())


@route(r'/organization/login')
class OrganizationLoginHandler(PersonalLoginHandler):

    def check_org_password(self, org_code, username, password):
        remote_ip = self.get_client_ip()
        logging.info('remote_ip: %s', remote_ip)
        base_server = config.get_config('sso_auth.base_server')
        organization_login_api = config.get_config('sso_auth.organization_login_api')
        organization_login_url = urljoin(base_server, organization_login_api)
        logging.info('organization login url %s', organization_login_url)
        json_data = {"orgCode": org_code, "account": username, "password": hashlib.md5(password.encode()).hexdigest(), "reqMacIp": remote_ip}
        logging.debug('organization login json_data %s', json_data)
        try:
            res = requests.post(organization_login_url, json=json_data, timeout=5, verify=False)
            if res.status_code != 200:
                logging.error('organization login request text: %s', res.text)
                return False, f'organization login request failed, status code: {res.status_code}'
            res_data = res.json()
            if str(res_data['data']['resultCode']) != '0':
                logging.error('organization login response data: %s', res_data)
                return False, f"organization login response data, resultCode: {res_data['data']['resultCode']}, msg: {res_data['data']['resultMsg']}"
            organization_biz_code = config.get_config('sso_auth.organization_biz_code')
            system_data = [item for item in res_data['data']['systemList'] if str(item['bizCode']) == str(organization_biz_code)]
            if not system_data:
                logging.info('organization login response systemList data: %s', res_data['data']['systemList'])
                return False, f'not found valid system data, config organization_biz_code: {organization_biz_code}'

            data = {
                'uid': system_data[0]['accountList'][0]['accountId'],
                'ext_uname': system_data[0]['accountList'][0]['accountId'],
                'username': system_data[0]['accountList'][0]['accountName'],
            }
        except Exception as e:
            logging.error(e)
            return False, 'check organization login exception'
        return True, data

    def post(self, *args, **kwargs):
        body = self.get_json_body()
        org_code = body.get('org_code')
        username = body.get('username')
        password = body.get('password')
        if not org_code or not username or not password:
            return self.error(INVALID_PARAMETERS)

        flag, msg = self.check_captcha()
        if not flag:
            return self.error(msg, status_code=400)

        flag, data = self.check_org_password(org_code, username, password)
        if not flag:
            return self.error(data)

        role = db_session.query(Role).filter(Role.name == 'ops_role').first()
        user = User.make_user(
            uid=data['uid'], ext_uname=data['ext_uname'], username=data['username'], login_method='organization', _from='nafmii', role_id=role.id
        )
        self.session['proxy_user_id'] = str(user.id)
        return self.data(user.to_dict())


@route(r'/mock/auth/mobile/login.json')
class MockPersonalAuthHandler(BaseHandler):
    ACCOUNT_PASSWORD_MAP = {
        'personal_biz_user1': {
            "data": {
                "resultCode": "0",
                "resultMsg": "success",
                "systemList": [
                    {
                        "bizCode": "10001",
                        "bizName": "NAFMII平台智能文本识别",
                        "bizShortName": "智能文本识别",
                        "accountList": [
                            {"accountId": "3005728", "accountCode": "personal_biz_user1", "accountName": "注册业务用户", "roleList": ['bizRole202501']}
                        ],
                    }
                ],
            }
        },
        'personal_ops_user1': {
            "data": {
                "resultCode": "0",
                "resultMsg": "success",
                "systemList": [
                    {
                        "bizCode": "10001",
                        "bizName": "NAFMII平台智能文本识别",
                        "bizShortName": "智能文本识别",
                        "accountList": [
                            {"accountId": "30057281", "accountCode": "personal_ops_user1", "accountName": "注册运维用户", "roleList": ['bizRole202502']}
                        ],
                    }
                ],
            }
        },
    }

    def post(self, *args, **kwargs):
        body = self.get_json_body(binary=False)
        account = body['account']
        password = body['password']
        if account not in self.ACCOUNT_PASSWORD_MAP:
            return self.send_json({"data": {"resultCode": "-1", "resultMsg": "账号错误"}}, binary=False)
        if password != hashlib.md5('123456'.encode()).hexdigest():
            return self.send_json({"data": {"resultCode": "-1", "resultMsg": "密码错误"}}, binary=False)
        return self.send_json(self.ACCOUNT_PASSWORD_MAP[account], binary=False)


@route(r'/mock/auth/accountInner/login.json')
class MockOrganizationAuthHandler(BaseHandler):
    ACCOUNT_PASSWORD_MAP = {
        'org_biz_user1': {
            "data": {
                "resultCode": "0",
                "resultMsg": "success",
                "systemList": [
                    {
                        "bizCode": "2025",
                        "bizName": "NAFMII平台智能文本识别",
                        "bizShortName": "智能文本识别",
                        "accountList": [
                            {
                                "accountId": "3005333",
                                "accountCode": "org_biz_user1",
                                "accountName": "机构业务用户",
                                "roleList": ['bizRole202501'],
                            }
                        ],
                    }
                ],
            }
        },
        'org_ops_user1': {
            "data": {
                "resultCode": "0",
                "resultMsg": "success",
                "systemList": [
                    {
                        "bizCode": "2025",
                        "bizName": "NAFMII平台智能文本识别",
                        "bizShortName": "智能文本识别",
                        "accountList": [
                            {
                                "accountId": "30053331",
                                "accountCode": "org_ops_user1",
                                "accountName": "机构运维用户",
                                "roleList": ['bizRole202502'],
                            }
                        ],
                    }
                ],
            }
        },
    }

    def post(self, *args, **kwargs):
        body = self.get_json_body(binary=False)
        account = body['account']
        password = body['password']
        org_code = body['orgCode']
        req_mac_ip = body['reqMacIp']
        if org_code != '0000':
            return self.send_json({"data": {"resultCode": "-1", "resultMsg": "机构编码错误"}}, binary=False)
        if account not in self.ACCOUNT_PASSWORD_MAP:
            return self.send_json({"data": {"resultCode": "-1", "resultMsg": "账号错误"}}, binary=False)
        if password != hashlib.md5('123456'.encode()).hexdigest():
            return self.send_json({"data": {"resultCode": "-1", "resultMsg": "密码错误"}}, binary=False)
        return self.send_json(self.ACCOUNT_PASSWORD_MAP[account], binary=False)
