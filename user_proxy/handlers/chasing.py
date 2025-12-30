# -*-coding:utf-8-*-
# pylint:disable=too-many-locals
import datetime
import hashlib
import logging
from hashlib import md5
from urllib.parse import urljoin

import requests
from sqlalchemy.orm.attributes import flag_modified

from user_proxy import config
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url
from user_proxy.db import db_session
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.handlers.message import USER_NOT_EXISTS, PERMISSION_DENIED
from user_proxy.models.user import User
from user_proxy.utils.cas import create_url


@route(r'/chasing/sso-login')
class ChasingSSOLoginHandler(BaseHandler):
    @staticmethod
    def get_current_time():
        return datetime.datetime.now().strftime('%Y%m%d%H%M%S')

    @staticmethod
    def generate_sign(signs):
        sign_source_str = ''.join([str(item) for item in signs])
        logging.info('generate mac source str: %s', sign_source_str)
        return md5(sign_source_str.encode()).hexdigest()

    def get(self, *args, **kwargs):
        token = self.get_argument('token', None)
        subpath = config.get_config("webif.redirect_subpath", '')
        trident_server = config.get_config('chasing_auth.trident_server')
        trident_base = urljoin(trident_server or self.origin_host, subpath.lstrip('/'))
        origin_url = f'{trident_base}/api/v1/chasing/sso-login'
        app = self.get_argument('app', None)
        origin = self.get_argument('origin', None)

        base_server = config.get_config('chasing_auth.base_server')
        app_code = config.get_config('chasing_auth.app_code')
        auth_code = config.get_config('chasing_auth.auth_code')
        current_time = self.get_current_time()
        if token:
            user_info_api = config.get_config('chasing_auth.user_info_api')
            target_code = config.get_config('chasing_auth.target_code')
            user_info_url = create_url(
                base_server,
                user_info_api,
                ('appCode', app_code),
                ('targetCode', target_code),
                ('timestamp', current_time),
                ('token', token),
                ('mac', self.generate_sign([str(app_code), str(target_code), current_time, token, auth_code])),
            )
            logging.info('user_info_url: %s', user_info_url)
            try:
                response = requests.get(user_info_url, verify=False, timeout=5)
                logging.info('response text: %s', response.text)
                if response.status_code != 200:
                    return self.error(f'get user_info error, status_code={response.status_code}', status_code=400)
                res_data = response.json()
                if str(res_data['status']) != '0':
                    return self.error('get user_info status error: %s, msg: %s', res_data['status'], res_data['msg'])
                ext_uname = res_data['data']['userInfo']['memberId']
            except Exception as e:
                logging.exception(e)
                return self.error('permission denied')
            user = db_session.query(User).filter(User.ext_uname == ext_uname, User.deleted == 0).first()
            if not user:
                return self.error(USER_NOT_EXISTS)
            if not user.allow_login:
                return self.error(PERMISSION_DENIED)
            user.user_data['uc_token'] = token
            flag_modified(user, 'user_data')
            db_session.commit()
            self.session['proxy_user_id'] = str(user.id)
            redirect_url = '/'
            if app and origin:
                redirect_url = get_off_redirect_url(app, user, origin_host=self.origin_host, origin=origin, direct_jump="1")
        else:
            sso_login_api = config.get_config('chasing_auth.sso_login_api')
            trident_args = []
            if app:
                trident_args.append(('app', app))
            if origin:
                trident_args.append(('origin', origin))
            origin_url = create_url(origin_url, None, *trident_args)
            url_args = [
                ('appCode', app_code),
                ('timeStamp', current_time),
                ('url', origin_url),
                ('mac', self.generate_sign([str(app_code), current_time, origin_url, auth_code])),
            ]
            redirect_url = create_url(base_server, sso_login_api, *url_args)
            logging.info('get_token_url: %s', redirect_url)
        return self.redirect(redirect_url)


@route(r"/mock/sso/login")
class MockSsoLoginHandler(BaseHandler):
    def get(self, *args, **kwargs):
        app_code = self.get_argument('appCode')
        url = self.get_argument('url')
        time_stamp = self.get_argument('timeStamp')
        mac = self.get_argument('mac')
        sign = hashlib.md5(''.join([app_code, time_stamp, url, 'FpaePvmDZHMOa2YF8MMz9ADhzO60L7oU']).encode()).hexdigest()
        assert sign == mac
        logging.error(url)
        return self.redirect(f'{url}?token=4fa71b53-b80f-4bab-8fe4-2fe09c222401' if '?' not in url else f'{url}&token=4fa71b53-b80f-4bab-8fe4-2fe09c222401')


@route(r"/mock/sso/getUserInfo")
class MockSsoUserInfoHandler(BaseHandler):
    def get(self, *args, **kwargs):
        app_code = self.get_argument('appCode')
        target_code = self.get_argument('targetCode')
        time_stamp = self.get_argument('timestamp')
        token = self.get_argument('token')
        assert token == '4fa71b53-b80f-4bab-8fe4-2fe09c222401'
        mac = self.get_argument('mac')
        sign = hashlib.md5(''.join([app_code, target_code, time_stamp, token, 'FpaePvmDZHMOa2YF8MMz9ADhzO60L7oU']).encode()).hexdigest()
        assert sign == mac
        return self.send_json(
            {
                "status": "0",
                "msg": "success",
                "data": {
                    "accountInfo": [],
                    "userInfo": {"memberId": "10000013", "loginName": "lxl668", "orgId": "9497", "permissionOrg": []},
                    "expireTime": "20200806112504",
                },
            },
            binary=False,
        )


@route(r"/mock/sync/user/queryUserInfo")
class MockSyncUserInfoHandler(BaseHandler):
    def post(self, *args, **kwargs):
        data = {
            "code": "000000",
            "message": "成功",
            "userInfoList": [
                {"memberId": "10000013", "loginName": "peiww", "userName": "裴武威", "status": 0, 'accountCode': "peiww", 'orgId': '00'},
                {"memberId": "20200615001", "loginName": "lxl668", "userName": "李小龙-sync", "status": 0, "accountCode": "lxl668", 'orgId': '111'},
                {'memberId': '20200615100011', 'userName': '信息技术中心1', 'status': 0, 'accountCode': 'xxjszx01', 'orgId': '10001'},
                {'memberId': '20200615100012', 'userName': '信息技术中心2', 'status': 0, 'accountCode': 'xxjszx02', 'orgId': '10001'},
                {'memberId': '20200615100013', 'userName': '信息技术中心3', 'status': 0, 'accountCode': 'xxjszx03', 'orgId': '10001'},
                {'memberId': '20200615100014', 'userName': '信息技术中心4', 'status': 0, 'accountCode': 'xxjszx04', 'orgId': '10001'},
                {'memberId': '20200615100015', 'userName': '信息技术中心5', 'status': 0, 'accountCode': 'xxjszx05', 'orgId': '10001'},
                {'memberId': '20200615100016', 'userName': '信息技术中心6', 'status': 0, 'accountCode': 'xxjszx06', 'orgId': '10001'},
                {'memberId': '20200615100021', 'userName': '投资银行管理部1', 'status': 0, 'accountCode': 'tzyhglb01', 'orgId': '10002'},
                {'memberId': '20200615100022', 'userName': '投资银行管理部2', 'status': 0, 'accountCode': 'tzyhglb02', 'orgId': '10002'},
                {'memberId': '20200615100023', 'userName': '投资银行管理部3', 'status': 0, 'accountCode': 'tzyhglb03', 'orgId': '10002'},
                {'memberId': '20200615100024', 'userName': '投资银行管理部4', 'status': 0, 'accountCode': 'tzyhglb04', 'orgId': '10002'},
                {'memberId': '20200615100025', 'userName': '投资银行管理部5', 'status': 0, 'accountCode': 'tzyhglb05', 'orgId': '10002'},
                {'memberId': '20200615100026', 'userName': '投资银行管理部6', 'status': 0, 'accountCode': 'tzyhglb06', 'orgId': '10002'},
                {'memberId': '20200615100031', 'userName': '债券融资一部1', 'status': 0, 'accountCode': 'zqrzyb01', 'orgId': '10003'},
                {'memberId': '20200615100032', 'userName': '债券融资一部2', 'status': 0, 'accountCode': 'zqrzyb02', 'orgId': '10003'},
                {'memberId': '20200615100033', 'userName': '债券融资一部3', 'status': 0, 'accountCode': 'zqrzyb03', 'orgId': '10003'},
                {'memberId': '20200615100034', 'userName': '债券融资一部4', 'status': 0, 'accountCode': 'zqrzyb04', 'orgId': '10003'},
                {'memberId': '20200615100035', 'userName': '债券融资一部5', 'status': 0, 'accountCode': 'zqrzyb05', 'orgId': '10003'},
                {'memberId': '20200615100036', 'userName': '债券融资一部6', 'status': 0, 'accountCode': 'zqrzyb06', 'orgId': '10003'},
                {'memberId': '20200615100041', 'userName': '债券融资二部1', 'status': 0, 'accountCode': 'zqrzerb01', 'orgId': '10004'},
                {'memberId': '20200615100042', 'userName': '债券融资二部2', 'status': 0, 'accountCode': 'zqrzerb02', 'orgId': '10004'},
                {'memberId': '20200615100043', 'userName': '债券融资二部3', 'status': 0, 'accountCode': 'zqrzerb03', 'orgId': '10004'},
                {'memberId': '20200615100044', 'userName': '债券融资二部4', 'status': 0, 'accountCode': 'zqrzerb04', 'orgId': '10004'},
                {'memberId': '20200615100045', 'userName': '债券融资二部5', 'status': 0, 'accountCode': 'zqrzerb05', 'orgId': '10004'},
                {'memberId': '20200615100046', 'userName': '债券融资二部6', 'status': 0, 'accountCode': 'zqrzerb06', 'orgId': '10004'},
                {'accountCode': 'gqrzb01', 'memberId': '20200615100051', 'orgId': '10005', 'status': 0, 'userName': '股权融资部1'},
                {'accountCode': 'gqrzb02', 'memberId': '20200615100052', 'orgId': '10005', 'status': 0, 'userName': '股权融资部2'},
                {'accountCode': 'gqrzb03', 'memberId': '20200615100053', 'orgId': '10005', 'status': 0, 'userName': '股权融资部3'},
                {'accountCode': 'gqrzb04', 'memberId': '20200615100054', 'orgId': '10005', 'status': 0, 'userName': '股权融资部4'},
                {'accountCode': 'gqrzb05', 'memberId': '20200615100055', 'orgId': '10005', 'status': 0, 'userName': '股权融资部5'},
                {'accountCode': 'gqrzb06', 'memberId': '20200615100056', 'orgId': '10005', 'status': 0, 'userName': '股权融资部6'},
                {'accountCode': 'bjtxb01', 'memberId': '20200615100061', 'orgId': '10006', 'status': 0, 'userName': '北京投行部1'},
                {'accountCode': 'bjtxb02', 'memberId': '20200615100062', 'orgId': '10006', 'status': 0, 'userName': '北京投行部2'},
                {'accountCode': 'bjtxb03', 'memberId': '20200615100063', 'orgId': '10006', 'status': 0, 'userName': '北京投行部3'},
                {'accountCode': 'bjtxb04', 'memberId': '20200615100064', 'orgId': '10006', 'status': 0, 'userName': '北京投行部4'},
                {'accountCode': 'bjtxb05', 'memberId': '20200615100065', 'orgId': '10006', 'status': 0, 'userName': '北京投行部5'},
                {'accountCode': 'bjtxb06', 'memberId': '20200615100066', 'orgId': '10006', 'status': 0, 'userName': '北京投行部6'},
                {'accountCode': 'shtxb01', 'memberId': '20200615100061', 'orgId': '10006', 'status': 0, 'userName': '上海投行部1'},
                {'accountCode': 'shtxb02', 'memberId': '20200615100062', 'orgId': '10006', 'status': 0, 'userName': '上海投行部2'},
                {'accountCode': 'shtxb03', 'memberId': '20200615100063', 'orgId': '10006', 'status': 0, 'userName': '上海投行部3'},
                {'accountCode': 'shtxb04', 'memberId': '20200615100064', 'orgId': '10006', 'status': 0, 'userName': '上海投行部4'},
                {'accountCode': 'shtxb05', 'memberId': '20200615100065', 'orgId': '10006', 'status': 0, 'userName': '上海投行部5'},
                {'accountCode': 'shtxb06', 'memberId': '20200615100066', 'orgId': '10006', 'status': 0, 'userName': '上海投行部6'},
                {'accountCode': 'zbscb01', 'memberId': '20200615100071', 'orgId': '10007', 'status': 0, 'userName': '资本市场部1'},
                {'accountCode': 'zbscb02', 'memberId': '20200615100072', 'orgId': '10007', 'status': 0, 'userName': '资本市场部2'},
                {'accountCode': 'zbscb03', 'memberId': '20200615100073', 'orgId': '10007', 'status': 0, 'userName': '资本市场部3'},
                {'accountCode': 'zbscb04', 'memberId': '20200615100074', 'orgId': '10007', 'status': 0, 'userName': '资本市场部4'},
                {'accountCode': 'zbscb05', 'memberId': '20200615100075', 'orgId': '10007', 'status': 0, 'userName': '资本市场部5'},
                {'accountCode': 'zbscb06', 'memberId': '20200615100076', 'orgId': '10007', 'status': 0, 'userName': '资本市场部6'},
                {'accountCode': 'cxddb01', 'memberId': '20200615100081', 'orgId': '10008', 'status': 0, 'userName': '持续督导部1'},
                {'accountCode': 'cxddb02', 'memberId': '20200615100082', 'orgId': '10008', 'status': 0, 'userName': '持续督导部2'},
                {'accountCode': 'cxddb03', 'memberId': '20200615100083', 'orgId': '10008', 'status': 0, 'userName': '持续督导部3'},
                {'accountCode': 'cxddb04', 'memberId': '20200615100084', 'orgId': '10008', 'status': 0, 'userName': '持续督导部4'},
                {'accountCode': 'cxddb05', 'memberId': '20200615100085', 'orgId': '10008', 'status': 0, 'userName': '持续督导部5'},
                {'accountCode': 'cxddb06', 'memberId': '20200615100086', 'orgId': '10008', 'status': 0, 'userName': '持续督导部6'},
                {'accountCode': 'fxglb01', 'memberId': '20200615100091', 'orgId': '10009', 'status': 0, 'userName': '风险管理部1'},
                {'accountCode': 'fxglb02', 'memberId': '20200615100092', 'orgId': '10009', 'status': 0, 'userName': '风险管理部2'},
                {'accountCode': 'fxglb03', 'memberId': '20200615100093', 'orgId': '10009', 'status': 0, 'userName': '风险管理部3'},
                {'accountCode': 'fxglb04', 'memberId': '20200615100094', 'orgId': '10009', 'status': 0, 'userName': '风险管理部4'},
                {'accountCode': 'fxglb05', 'memberId': '20200615100095', 'orgId': '10009', 'status': 0, 'userName': '风险管理部5'},
                {'accountCode': 'fxglb06', 'memberId': '20200615100096', 'orgId': '10009', 'status': 0, 'userName': '风险管理部6'},
                {'accountCode': 'gsld01', 'memberId': '202006151000101', 'orgId': '100010', 'status': 0, 'userName': '公司领导1'},
                {'accountCode': 'gsld02', 'memberId': '202006151000102', 'orgId': '100010', 'status': 0, 'userName': '公司领导2'},
                {'accountCode': 'gsld03', 'memberId': '202006151000103', 'orgId': '100010', 'status': 0, 'userName': '公司领导3'},
                {'accountCode': 'gsld04', 'memberId': '202006151000104', 'orgId': '100010', 'status': 0, 'userName': '公司领导4'},
                {'accountCode': 'gsld05', 'memberId': '202006151000105', 'orgId': '100010', 'status': 0, 'userName': '公司领导5'},
                {'accountCode': 'gsld06', 'memberId': '202006151000106', 'orgId': '100010', 'status': 0, 'userName': '公司领导6'},
            ],
        }

        return self.send_json(data, binary=False)


@route(r"/mock/sync/org/queryOrgInfo")
class MockSyncDeptHandler(BaseHandler):
    def post(self, *args, **kwargs):
        data = {
            "code": "000000",
            "message": "成功",
            "orgInfoList": [
                {
                    "orgId": "00",
                    "orgName": "财富管理部",
                    "parentId": "9500",
                },
                {
                    "orgId": "111",
                    "orgName": "测试1",
                    "parentId": "202007135096",
                },
                {
                    "orgId": "10001",
                    "orgName": "信息技术中心",
                    "parentId": "-1",
                },
                {
                    "orgId": "10002",
                    "orgName": "投资银行管理部",
                    "parentId": "-1",
                },
                {
                    "orgId": "10003",
                    "orgName": "债券融资一部",
                    "parentId": "-1",
                },
                {
                    "orgId": "10004",
                    "orgName": "债券融资二部",
                    "parentId": "-1",
                },
                {
                    "orgId": "10005",
                    "orgName": "股权融资部",
                    "parentId": "-1",
                },
                {
                    "orgId": "10006",
                    "orgName": "北京投行部",
                    "parentId": "-1",
                },
                {
                    "orgId": "10006",
                    "orgName": "上海投行部",
                    "parentId": "-1",
                },
                {
                    "orgId": "10007",
                    "orgName": "资本市场部",
                    "parentId": "-1",
                },
                {
                    "orgId": "10008",
                    "orgName": "持续督导部",
                    "parentId": "-1",
                },
                {
                    "orgId": "10009",
                    "orgName": "风险管理部",
                    "parentId": "-1",
                },
                {
                    "orgId": "100010",
                    "orgName": "公司领导",
                    "parentId": "-1",
                },
            ],
        }

        return self.send_json(data, binary=False)
