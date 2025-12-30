import datetime
from urllib.parse import urljoin, urlencode

from sqlalchemy.orm.attributes import flag_modified

from user_proxy import config
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url
from user_proxy.db import db_session
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.utils.cas import create_url
from user_proxy.utils.cms_auth import gen_auth_string, validate_from_eac


@route(r'/cms/sso-login')
class CmsSSOLoginHandler(BaseHandler):
    def get(self, *args, **kwargs):
        # 第一次跳转
        subpath = config.get_config("webif.redirect_subpath", '')
        base_url = urljoin(self.origin_host, subpath.lstrip('/'))
        ias_id = config.get_config('cms_auth.IASID')
        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        return_url = '{}/api/v1/cms/sso-login/callback'.format(base_url.rstrip('/'))
        url_args = []
        if origin := self.get_argument('origin', ''):
            url_args.append(('origin', origin))
        if url_host := self.get_argument('host', None):
            url_args.append(('host', url_host))
        if custom_system := self.get_argument('custom_system', ''):
            url_args.append(('custom_system', custom_system))
        if app := self.get_argument('app', ''):
            url_args.append(('app', app))
        return_url = urljoin(return_url, '?{}'.format(urlencode(url_args)))
        ias_key = config.get_config("cms_auth.IASKEY")
        auth_string = gen_auth_string(ias_id, ias_key, timestamp, return_url)
        post_url = config.get_config('cms_auth.POSTURL')
        return self.render(
            'cms_auth.html', post_url=post_url, ias_id=ias_id, timestamp=timestamp, ReturnURL='ReturnURL', return_url=return_url, auth_string=auth_string
        )


@route(r'/cms/sso-login/callback')
class CMSSSOLoginCallbackHandler(BaseHandler):
    # pylint:disable=too-many-locals
    def post(self, *args, **kwargs):
        result = self.get_argument('Result', None)
        ias_id = self.get_argument('IASID')
        timestamp = self.get_argument('TimeStamp')
        error_desc = self.get_argument('ErrorDescription')
        auth_string = self.get_argument('Authenticator')
        user_account = self.get_argument('UserAccount')
        custom_system = self.get_argument('custom_system', None)
        ias_key = config.get_config("cms_auth.IASKEY")
        validated = validate_from_eac(ias_id, ias_key, timestamp, user_account, result, error_desc, auth_string)
        if validated:
            user = User.make_user(uid=user_account, ext_uname=user_account, username=user_account, _from='cms')
            if not user:
                return self.error('permission denied')
            user.user_data['custom_system'] = custom_system
            flag_modified(user, 'user_data')
            db_session.commit()
            self.session['proxy_user_id'] = str(user.id)
            url_args = []
            if origin := self.get_argument('origin', ''):
                url_args.append(('origin', origin))
            if url_host := self.get_argument('host', None):
                url_args.append(('host', url_host))
            if app := self.get_argument('app', ''):
                url_args.append(('sys', app))
                after_login_url = config.get_config('cms_auth.AFTER_LOGIN')
            else:
                after_login_url = '/'
            redirect_url = self.gen_redirect_url(after_login_url)
            url = create_url(redirect_url, None, *url_args)
            self.redirect(url)
        else:
            self.clear_all_cookies()
            return self.error('permission denied')


@route(r'/cms/sso-login-2')
class CMSSSOLogin2Handler(BaseHandler):
    """
    glazer使用
    """

    def get(self, *args, **kwargs):
        user_account = self.get_argument('UserAccount')
        app = self.get_argument('app')
        origin = self.get_argument('origin')
        user = User.make_user(uid=user_account, ext_uname=user_account, username=user_account, _from='cms')
        if not user:
            return self.error('permission denied')

        self.session['proxy_user_id'] = str(user.id)
        url = get_off_redirect_url(app, user, origin_host=self.origin_host, origin=origin)
        if not url:
            return self.error('sys: {} not config'.format(app))
        self.redirect(url)
