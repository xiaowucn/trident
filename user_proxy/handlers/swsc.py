import datetime
import logging
from urllib.parse import urljoin, urlencode

from user_proxy import config
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.utils.cas import create_url
from user_proxy.utils.cms_auth import gen_auth_string, validate_from_eac


@route(r'/swsc/sso-login')
class SWSCSSOLoginHandler(BaseHandler):
    def get(self, *args, **kwargs):
        # 第一次跳转
        subpath = config.get_config("webif.redirect_subpath", '')
        base_url = urljoin(self.origin_host, subpath.lstrip('/'))
        ias_id = config.get_config('swsc_auth.IASID')
        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        origin = self.get_argument('origin', '')
        return_url = '{}/api/v1/swsc/sso-login/callback'.format(base_url.rstrip('/'))
        url_args = []
        if origin:
            url_args.append(('origin', origin))
        url_host = self.get_argument('host', None)
        if url_host:
            url_args.append(('host', url_host))
        app = self.get_argument('app', 'autodoc_overall')
        url_args.append(('app', app))
        return_url = urljoin(return_url, '?{}'.format(urlencode(url_args)))
        ias_key = config.get_config("swsc_auth.IASKEY")
        auth_string = gen_auth_string(ias_id, ias_key, timestamp, return_url)
        post_url = config.get_config('swsc_auth.POSTURL')
        logging.info(
            'render html, post_url: %s, ias_id: %s, timestamp: %s, return_url: %s, auth_string: %s', post_url, ias_id, timestamp, return_url, auth_string
        )
        return self.render(
            'cms_auth.html', post_url=post_url, ias_id=ias_id, timestamp=timestamp, ReturnURL='ReturnURL', return_url=return_url, auth_string=auth_string
        )


@route(r'/swsc/sso-login/callback')
class SWSCSSOLoginCallbackHandler(BaseHandler):
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
        ias_key = config.get_config("swsc_auth.IASKEY")
        validated = validate_from_eac(ias_id, ias_key, timestamp, user_account, result, error_desc, auth_string)
        if validated:
            user = User.make_user(uid=user_account, ext_uname=user_account, username=user_account, _from='swsc')
            if not user:
                return self.error('permission denied')
            self.session['proxy_user_id'] = str(user.id)
            url_args = []
            if origin:
                url_args.append(('origin', origin))
            if url_host:
                url_args.append(('host', url_host))
            after_login_url = config.get_config('swsc_auth.AFTER_LOGIN')
            if after_login_url:
                url_args.append(('sys', app))
            redirect_url = self.gen_redirect_url(after_login_url)
            url = create_url(redirect_url, None, *url_args)
            self.redirect(url)
        else:
            logging.info(
                'validate from eac failed, ias_id: %s, ias_key: %s, timestamp: %s, user_account: %s, result: %s, error_desc: %s, auth_string: %s',
                ias_id,
                ias_key,
                timestamp,
                user_account,
                result,
                error_desc,
                auth_string,
            )
            self.clear_all_cookies()
            return self.error('permission denied')
