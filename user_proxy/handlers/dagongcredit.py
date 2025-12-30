# -*-coding:utf-8-*-
import base64
from urllib.parse import urljoin, parse_qs

from user_proxy import config
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url, get_user_sys_permission
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User


@route('/dagongcredit/sso-login')
class DagongcreditSSOLoginHandler(BaseHandler):

    def get(self, *args, **kwargs):
        token = self.get_argument('token')
        sys = self.get_argument('sys', 'generator')
        origin = self.get_argument('origin', '')
        user_info_str = base64.b64decode(token).decode('utf-8')
        params = parse_qs(user_info_str)
        user_id = params.get('user_id', [None])[0]
        username = params.get('username', [None])[0]
        if not user_id or not username:
            return self.error('用户信息错误：%s', token)
        user = User.make_user(uid=user_id, ext_uname=user_id, username=username, _from='dagongcredit')
        if not user:
            return self.error('permission denied', status_code=403)

        self.session['proxy_user_id'] = str(user.id)
        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))
        if sys:
            url = get_off_redirect_url(sys, user, origin_host=self.origin_host, origin=origin)
            if not url:
                return self.error('sys: %s not config', sys)
            return self.redirect(url)
        return self.redirect(trident_base)


@route('/dagongcredit/user-info')
class DagongcreditUserInfoHandler(BaseHandler):
    def get(self, *args, **kwargs):
        ext_uname = self.get_argument('user_id')
        username = self.get_argument('username')
        sys = self.get_argument('sys')
        user = User.make_user(uid=ext_uname, ext_uname=ext_uname, username=username, _from='dagongcredit')
        if not user:
            return self.error('user not existed', status_code=404)
        permission = get_user_sys_permission(user, sys)
        return self.send_json(
            {
                'ext_uname': ext_uname,
                'username': username,
                "permission": ','.join(permission),
                "ext_sys": config.get_config('sys'),
            },
            binary=False,
        )
