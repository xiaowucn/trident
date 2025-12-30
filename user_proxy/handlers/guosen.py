import datetime
import logging
from urllib.parse import urljoin, urlencode

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.utils.cas import create_url
from user_proxy.utils.cms_auth import gen_auth_string, validate_from_eac


@route(r'/guosen/sso-login')
class GUOSENSSOLoginHandler(BaseHandler):
    def get(self, *args, **kwargs):
        # 第一次跳转
        subpath = config.get_config("webif.redirect_subpath", '')
        base_url = urljoin(self.origin_host, subpath.lstrip('/'))
        ias_id = config.get_config('guosen_auth.IASID')
        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        origin = self.get_argument('origin', '')
        return_url = '{}/api/v1/guosen/sso-login/callback'.format(base_url.rstrip('/'))
        url_args = []
        if origin:
            url_args.append(('origin', origin))
        url_host = self.get_argument('host', None)
        if url_host:
            url_args.append(('host', url_host))
        app = self.get_argument('app', 'autodoc_overall')
        url_args.append(('app', app))
        return_url = urljoin(return_url, '?{}'.format(urlencode(url_args)))
        ias_key = config.get_config("guosen_auth.IASKEY")
        auth_string = gen_auth_string(ias_id, ias_key, timestamp, return_url)
        post_url = config.get_config('guosen_auth.POSTURL')
        return_url_key = config.get_config('guosen_auth.ReturnURL', 'ReturnURL')
        return self.render(
            'cms_auth.html', post_url=post_url, ias_id=ias_id, timestamp=timestamp, ReturnURL=return_url_key, return_url=return_url, auth_string=auth_string
        )


@route(r'/guosen/sso-login/callback')
class GUOSENSSOLoginCallbackHandler(BaseHandler):
    # pylint:disable=too-many-locals
    def post(self, *args, **kwargs):
        result = self.get_argument('Result', None)
        ias_id = self.get_argument('IASID')
        timestamp = self.get_argument('TimeStamp')
        error_desc = self.get_argument('ErrorDescription')
        auth_string = self.get_argument('Authenticator')
        user_account = self.get_argument('UserAccount')
        origin = self.get_argument('origin', '')
        url_host = self.get_argument('host', None)
        app = self.get_argument('app', 'autodoc_overall')
        ias_key = config.get_config("guosen_auth.IASKEY")
        logging.debug(
            'parameter: IASID=%s, TimeStamp=%s, ErrorDescription=%s, Authenticator=%s, UserAccount=%s', ias_id, timestamp, error_desc, auth_string, user_account
        )
        validated = validate_from_eac(ias_id, ias_key, timestamp, user_account, result, error_desc, auth_string)
        if validated:
            if config.get_config('unify_auth.check_sso_login_by_sync'):
                user = db_session.query(User).filter(User.ext_uname == user_account, User.deleted == 0).first()
                if user and user.user_data.get('ustatus') != '0':
                    return self.error('用户已禁用')
            else:
                user = User.make_user(uid=user_account, ext_uname=user_account, username=user_account)
            if not user:
                return self.error('权限不足')
            self.session['proxy_user_id'] = str(user.id)
            after_login_url = config.get_config('guosen_auth.AFTER_LOGIN')
            url_args = []
            if origin:
                url_args.append(('origin', origin))
            if url_host:
                url_args.append(('host', url_host))
            redirect_subpath = config.get_config('webif.redirect_subpath')
            if app == 'trident':
                url = urljoin(self.origin_host, redirect_subpath).rstrip('/') + '/#/project'
                return self.redirect(url)
            url_args.append(('sys', app))
            redirect_url = self.gen_redirect_url(after_login_url)
            url = create_url(redirect_url, None, *url_args)
            self.redirect(url)
        else:
            self.clear_all_cookies()
            return self.error('permission denied')


@route(r'/guosen/users/synchronize')
class GUOSENUserSyncHandler(BaseHandler):
    def post(self, *args, **kwargs):
        body = self.get_json_body(binary=False)
        user_list = body.get('user_list', [])
        db_users_map = dict(db_session.query(User.ext_uname, User).filter(User.deleted == 0, User.user_data.op('->>')('ext_sys') != 'self'))
        add_users = []
        for user_info in user_list:
            uid, uname, ustatus = user_info
            if uid in db_users_map:
                add_users.append(uid)
            allow_login = str(ustatus) == '0'
            User.make_user(uid, uid, user_name=uname, ustatus=str(ustatus), allow_login=allow_login)
        if config.get_config('webif.feature.increase_sync'):
            logging.info('sync users: %s', user_list)
            redundant_users = []
        else:
            redundant_users = [ext_uname for ext_uname in db_users_map if ext_uname not in add_users]
            logging.info('redundant users: %s', redundant_users)
        return self.data({"add_users": redundant_users})
