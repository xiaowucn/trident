import logging
import traceback

import ldap

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.handlers.message import INVALID_USERNAME_OR_PASSWD, LDAP_ERROR
from user_proxy.models.user import User

LDAP_VERSION = config.get_config("ldap.version")
LDAP_URI = config.get_config("ldap.uri")
LDAP_SEARCH_BASE = config.get_config("ldap.search_base")
LDAP_FILTER = config.get_config("ldap.filter")
LDAP_ATTRLIST = config.get_config("ldap.attrlist")
LDAP_ADMIN_DN = config.get_config("ldap.admin_dn")
LDAP_ADMIN_PASSWORD = config.get_config("ldap.admin_password")

if isinstance(LDAP_ATTRLIST, str):
    LDAP_ATTRLIST = list(LDAP_ATTRLIST)


def get_conn():
    conn = ldap.initialize(LDAP_URI)
    conn.set_option(ldap.OPT_REFERRALS, 0)
    conn.protocol_version = LDAP_VERSION and int(LDAP_VERSION) or ldap.VERSION3
    return conn


def ldap_search_and_bind(conn, uid, password):
    results = conn.search_s(LDAP_SEARCH_BASE, ldap.SCOPE_SUBTREE, LDAP_FILTER % (uid,), attrlist=LDAP_ATTRLIST)
    results = [item for item in results if item[0]]
    if results:
        for result in results:
            user_dn, attrs = result
            logging.debug("ldap result: %s", result)
            try:
                if config.get_config('sys') == 'cgs':
                    conn1 = get_conn()
                    conn1.simple_bind_s(user_dn, password)
                    conn1.unbind_s()
                else:
                    conn.simple_bind_s(user_dn, password)
            except ldap.LDAPError:
                logging.error("[%s] fail to bind", user_dn)
                continue
            else:
                attrlist = []
                for key in LDAP_ATTRLIST:
                    if key in attrs:
                        attrlist.append(attrs[key][0])
                    else:
                        attrlist.append(None)
                return True, (user_dn, attrlist)
        return False, "account/password not match"
    return False, "can not find user"


def ldap_login(uid, password):
    # 初始化连接
    try:
        conn = get_conn()
    except ldap.LDAPError:
        logging.error(traceback.format_exc())
        return False, LDAP_ERROR

    # ldap admin 登录
    try:
        conn.simple_bind_s(LDAP_ADMIN_DN, LDAP_ADMIN_PASSWORD)
    except ldap.LDAPError as e:
        logging.error(traceback.format_exc())
        return False, LDAP_ERROR

    # 查找 uid 并尝试逐个登录
    flag, ret_val = ldap_search_and_bind(conn, uid, password)
    if not flag:
        return False, INVALID_USERNAME_OR_PASSWD

    # 关闭连接
    conn.unbind_s()
    return True, ret_val


def login_precheck(uid):
    user = db_session.query(User).filter(
        User.ext_uname == uid, not User.permissions.any(User.P_MANAGE), User.resign.is_(False), User.deleted == 0
    ).first()
    return user
