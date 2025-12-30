# pylint: disable=too-many-locals
import base64
import logging
from urllib.parse import urljoin

import requests

from user_proxy import config
from user_proxy.handlers.base import route, BaseHandler, permission_auth
from user_proxy.models.user import User
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url


@route(r'/citics/sso-login')
class CITICSSSOLoginHandler(BaseHandler):
    @staticmethod
    def save_user(user_id, username, email):
        if not user_id:
            return None
        user = User.make_user(user_id, user_id, username=username, email=email)
        return user

    def sso_login(self, *args, **kwargs):
        session_data = self.get_argument('SESSION_DATA')
        app = self.get_argument('app', None)
        origin = self.get_argument('origin', None)
        auth_host = config.get_config('citics_auth.auth_host')
        auth_api = config.get_config('citics_auth.auth_api')
        auth_url = urljoin(auth_host, auth_api)

        app_id = config.get_config('citics_auth.app_id')
        app_secret = config.get_config('citics_auth.app_secret')

        auth_string = 'Basic ' + base64.b64encode((app_id + ':' + app_secret).encode()).decode()
        logging.info('session_data: %s', session_data)
        logging.info('auth_string: %s', auth_string)

        try:
            res = requests.post(auth_url, data={'sessionData': session_data}, headers={'Authorization': auth_string})
        except Exception as e:
            logging.exception(e)
            return self.error('permission denied')
        try:
            user_data = res.json()
        except Exception as e:
            logging.error('headers: %s', res.headers)
            logging.error('body: %s', res.text)
            logging.exception(e)
            return self.error('permission denied')
        else:
            logging.info('user_data: %s', user_data)
            user = self.save_user(user_data['uid'], user_data['name'], email=user_data.get('email'))
            if not user:
                return self.error('permission denied')
            self.session['proxy_user_id'] = str(user.id)

            if app:
                url = get_off_redirect_url(app, user, origin_host=self.origin_host, origin=origin)
                if not url:
                    return self.error('sys: {} not config'.format(app))
                return self.redirect(url)
            return self.redirect('/')

    def get(self, *args, **kwargs):
        self.sso_login(*args, **kwargs)

    def post(self, *args, **kwargs):
        self.sso_login(*args, **kwargs)


@route(r'/citics/stronghold/viewer')
class CITICSStrongholdHandler(BaseHandler):
    @permission_auth()
    def get(self, *args, **kwargs):
        qb_id = self.get_argument('qb_id')
        sub_path = config.get_config("unify_auth.auth_config.auth_stronghold.subpath", "")
        url = f"/api/v1/get-off?sys=stronghold&origin=/{sub_path}#/file-view/{qb_id}"
        return self.redirect(url)
