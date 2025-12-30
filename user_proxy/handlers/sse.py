# pylint: disable=too-many-return-statements
import logging
import json
import random

import requests
from wtforms import Form, StringField
from wtforms.validators import DataRequired

from user_proxy.config import get_config
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User


@route(r'/sse/token-login')
class SSETokenLoginHandler(BaseHandler):
    class PostForm(Form):
        token = StringField('token', [DataRequired()])

    def post(self, *args, **kwargs):
        form = SSETokenLoginHandler.PostForm.from_json(self.get_json_body())
        if not form.validate():
            return self.error('表单错误', str(form.errors))

        token_login_url = get_config('sse.token_check_url')
        guid = get_config('sse.guid')
        if not token_login_url:
            return self.error('未找到服务地址')
        if not guid:
            return self.error('未找到用户组ID')

        headers = {"access-key": get_config("sse.access_key")}
        json_payload = {"params": {"token": form.token.data, "guid": str(guid)}}
        rsp = requests.post(token_login_url, json=json_payload, headers=headers)
        if rsp.status_code != 200:
            logging.error('获取用户信息失败: http_code=%s', rsp.status_code)
            return self.error('获取用户信息失败')
        response_data = rsp.json()
        if response_data.get("success") is not True:
            logging.error('获取用户信息失败: response_data=%s', json.dumps(response_data))
            return self.error('获取用户信息失败')

        user_data = response_data.get("result", {}).get("user", {})
        if not user_data:
            return self.error('获取用户信息失败')

        user = User.make_user(uid=user_data["id"], ext_uname=user_data["fullname"], username=user_data["username"], _from='sse', token=form.token.data)
        self.session['proxy_user_id'] = str(user.id)
        user.session_id = self.session.session_id
        return self.data(user.to_dict())


@route(r'/sse/config')
class SSEConfigHandler(BaseHandler):
    def get(self, *args, **kwargs):
        return self.data(
            {
                "service_address": get_config('sse.service_address'),
                "login_page_url": get_config('sse.login_page_url'),
                "guid": get_config('sse.guid'),
                "logout_url": get_config('sse.logout_url'),
                "access_key": get_config('sse.access_key'),
                "redirect": get_config('sse.redirect'),
            },
            handshake=True,
        )


@route(r'/sse/mock/token/check')
class SSEMockTokenCheckHandler(BaseHandler):
    def post(self, *args, **kwargs):
        logging.info('access-key: %s', self.request.headers.get('access-key'))
        data = self.get_json_body()
        in_token = data['params']['token']
        if in_token.startswith('S|'):
            in_token = 'I|' + in_token[2:]
        return self.send_json(
            {
                "id": "1567668013124",
                "result": {
                    "token": in_token,
                    "user": {
                        "id": 2622,
                        "username": "testUser",
                        "fullname": "测试用户",
                        "email": "test@sse.com.cn",
                    },
                },
                "success": True,
            }
        )


@route(r'/sse/mock/login/page')
class SSEMockLoginPageHandler(BaseHandler):
    def get(self, *args, **kwargs):
        redirect = self.get_argument('redirect')
        token = 'S|' + str(random.randint(10000, 100000))
        return self.redirect(f'{redirect}?token={token}')


@route(r'/sse/mock/logout')
class SSEMockLogoutHandler(BaseHandler):
    def get(self, *args, **kwargs):
        logging.info('access-key: %s', self.request.headers.get('access-key'))
        data = self.get_json_body()
        _ = data['params']['token']
        return self.send_json({"success": True})
