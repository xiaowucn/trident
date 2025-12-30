# CYC: skip-file
# pylint: disable=too-many-locals
import logging
from urllib.parse import urljoin

from casdoor import CasdoorSDK

from user_proxy import config
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User


@route(r'/casdoor/sso-login')
class CASDoorSSOLoginHandler(BaseHandler):
    def ensure_ext_sys(self, user_data):
        if user_data['signupApplication'] == 'WeChat':
            return User.EXT_SYS_WECHAT
        if user_data['type'].startswith('vip'):
            return User.EXT_SYS_VIP
        return None

    def save_user(self, user_data):
        user = User.make_user(
            uid=user_data['AppUserId'] or None,
            uuid=user_data['id'] or None,
            ext_uname=user_data['name'],
            username=user_data['displayName'],
            signup_application=user_data['signupApplication'],
            _from='casdoor',
            ext_sys=self.ensure_ext_sys(user_data),
            app_user_type=user_data['type'],
        )
        return user

    def get(self, *args, **kwargs):
        code = self.get_argument('code', None)
        target_uri = self.get_argument('target_uri')

        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))

        endpoint = config.get_config('casdoor_auth.endpoint')
        client_id = config.get_config('casdoor_auth.client_id')
        client_secret = config.get_config('casdoor_auth.secret')
        org_name = config.get_config('casdoor_auth.org_name')
        certificate = config.get_config('casdoor_auth.cert')

        sdk = CasdoorSDK(
            endpoint,
            client_id,
            client_secret,
            certificate,
            org_name,
        )

        if code:
            access_token = sdk.get_oauth_token(code)
            logging.info('access_token: %s', access_token)
            user_data = sdk.parse_jwt_token(access_token)
            logging.info(user_data)
            user = self.save_user(user_data)
            self.session['proxy_user_id'] = str(user.id)
            redirect_url = urljoin(trident_base, target_uri)
        else:
            origin_url = '{}/api/v1/casdoor/sso-login?target_uri={}'.format(trident_base, target_uri)
            redirect_url = sdk.get_auth_link(origin_url, state='casdoor')
            redirect_url = f'{redirect_url}&silentSignin=1'
            logging.info('redirect to %s', redirect_url)
        return self.redirect(redirect_url)
