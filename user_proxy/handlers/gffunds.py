# -*-coding:utf-8-*-
# pylint:disable=too-many-locals, too-many-return-statements
import json
import logging

import requests
from utensils.util import generate_timestamp

from user_proxy import config
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User


@route(r'/gffunds/sso-login')
class GFFUNDSSSOLoginHandler(BaseHandler):
    def get(self, *args, **kwargs):
        session_id = self.get_argument('sessionId', None)
        if not session_id:
            return self.error('permission denied, miss sessionId')
        user_info_url = config.get_config('sso_auth.url')
        logging.info('sso auth url: %s', user_info_url)
        logging.info('sso auth session_id: %s', session_id)
        try:
            response = requests.post(user_info_url, json={'sessionId': session_id}, headers={"Content-Type": "application/json"}, verify=False, timeout=10)
            if response.status_code != 200:
                return self.error(f'get user info error, status_code = {response.status_code}')
            res_data = response.json()
            logging.info('get user info data: %s', res_data)
            if not res_data['success']:
                return self.error(f'get user_info failed, errcode: {res_data["errcode"]}, errmsg: {res_data["errmsg"]}')
            data = res_data['data']
            uid = data['userId']
            ext_uname = data['username']
            user_name = data['nickname']
            session_expire = data['sessionExpireTime'] * 60
        except Exception as e:
            logging.exception(e)
            return self.error('get user info service error')
        user = User.make_user(uid, ext_uname, user_name=user_name)
        if not user:
            return self.error('permission denied')
        self.session['proxy_user_id'] = str(user.id)
        sso_attribute_session_key = config.get_config('sso_auth.sso_attribute_session_key')
        self.set_cookie(sso_attribute_session_key, session_id, expires=generate_timestamp() + session_expire)
        self.session['customer_session_expire'] = session_expire
        url = '/'
        if sys := self.get_argument('sys', ''):
            # origin 会拼接在url中
            url = get_off_redirect_url(sys, user, origin_host=self.origin_host, origin=self.get_argument('origin', None))
            if not url:
                return self.error('sys: {} not config'.format(sys))
        return self.redirect(url)


@route('/mock/gffunds/sso/authorize')
class MockGFFUNDSSSOAuthHandler(BaseHandler):
    def post(self, *args, **kwargs):
        json_body = self.get_json_body(binary=False)
        if json_body.get('sessionId') != '1111':
            data = None
            success = False
            errmsg = "验证不通过！sessionId过期或者不存在。"
            errcode = 20001
        else:
            success = True
            errmsg = "请求成功"
            errcode = 0
            data = {
                "userId": "919",
                "username": "guxh",
                "nickname": "古旭宏",
                "empid": "",
                "sessionId": "sso:sessionId:guxh:4ded7aabbb234713984dfa85540ad6fd",
                "posNum": "ybyg",
                "posName": "一般员工",
                "orgNum": "xtyfz",
                "orgName": "系统研发组",
                "admin": False,
                "sessionExpireTime": 10,
                "password": None,
                "mobile": "",
                "faxno": "",
                "email": "",
            }
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.write(json.dumps({"success": success, "errmsg": errmsg, "errcode": errcode, "data": data}, ensure_ascii=False))
