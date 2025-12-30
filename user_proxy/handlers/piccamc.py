# -*-coding:utf-8-*-
import logging

import ldap

from user_proxy import config
from user_proxy.handlers.base import route
from user_proxy.handlers.message import (
    INVALID_PARAMETERS,
)
from user_proxy.handlers.proxy import LoginHandler
from user_proxy.models.user import User

LDAP_URI = config.get_config('ldap_ad_auth.ldap_uri')
LDAP_TIMEOUT = int(config.get_config('ldap_ad_auth.ldap_timeout', 3))
USER_SUFFIX = config.get_config('ldap_ad_auth.user_suffix')


def auth_ad(username: str, password: str):
    conn = None
    try:
        conn = ldap.initialize(LDAP_URI)
        conn.set_option(ldap.OPT_PROTOCOL_VERSION, ldap.VERSION3)
        conn.set_option(ldap.OPT_NETWORK_TIMEOUT, LDAP_TIMEOUT)

        bind_dn = f"{username}{USER_SUFFIX}"
        conn.simple_bind_s(bind_dn, password)
        logging.info("AD 认证成功：%s", bind_dn)
        return None
    except ldap.INVALID_CREDENTIALS as e:
        logging.error("身份验证失败！%s", e)
        return "身份验证失败！"
    except ldap.SERVER_DOWN as e:
        logging.error("AD 域连接失败！%s", e)
        return "AD 域连接失败！"
    except ldap.LDAPError as e:
        logging.error("身份验证未知异常！%s", e)
        return "身份验证未知异常！"
    finally:
        if conn is not None:
            try:
                conn.unbind_s()
            except Exception as e:
                logging.error("关闭 LDAP 连接时异常：%s", e)


@route(r'/ldap/ad-login')
class LdapADLoginHandler(LoginHandler):
    def post(self, *args, **kwargs):
        body = self.get_json_body()
        username = body.get('username')
        password = body.get('password')
        if not username or not password:
            return self.error(INVALID_PARAMETERS)

        flag, msg = self.check_captcha()
        if not flag:
            return self.error(msg)
        error_msg = auth_ad(username, password)
        if error_msg:
            return self.error(error_msg)
        user = User.make_user(uid=username, ext_uname=username, username=username, _from='ldap')
        self.session['proxy_user_id'] = str(user.id)
        return self.data(user.to_dict())
