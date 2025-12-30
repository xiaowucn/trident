"""
民生证券单点登录
"""
# pylint:disable=too-many-locals
import base64
import logging
from urllib.parse import urljoin

from aiohttp import ClientSession, TCPConnector
from tornado.escape import to_unicode

from user_proxy import config
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.handlers.message import ACCOUNT_LOGIN_LIMIT
from user_proxy.models.user import User
from user_proxy.utils.cas import create_url


@route('/mszq/sso-login')
class MSZQSSOLoginHandler(BaseHandler):
    @staticmethod
    def save_user(ext_uname):
        user = User.make_user(uid=ext_uname, ext_uname=ext_uname, username=ext_uname, _from='mszq', custom_system='oa')
        return user

    async def get(self, *args, **kwargs):  # pylint:disable=invalid-overridden-method
        token_cookie_key = config.get_config('mszq_auth.token_cookie_key')
        auth_server = config.get_config('mszq_auth.auth_server')
        login_name_api = config.get_config('mszq_auth.login_name_api')
        oa_server = config.get_config('mszq_auth.oa_server')
        oa_login_api = config.get_config('mszq_auth.oa_login_api')
        oa_logout_api = config.get_config('mszq_auth.oa_logout_api')

        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))
        origin_url = '{}/api/v1/mszq/sso-login'.format(trident_base)
        if self.request.query:
            origin_url += f"?{self.request.query}"
        task_types = self.get_argument('task_types', '')

        url_args = [('targetredirecturl', origin_url)]
        if task_types:
            url_args.append(('task_types', task_types))
        token = self.get_cookie(token_cookie_key)
        if token:
            auth_url = urljoin(auth_server.rstrip('/'), login_name_api)
            auth_username = config.get_config('mszq_auth.auth_username')
            auth_password = config.get_config('mszq_auth.auth_password')

            auth_string = 'Basic ' + base64.b64encode((auth_username + ':' + auth_password).encode()).decode()
            logging.info('auth_url: %s, token: %s, auth_string: %s', auth_url, token, auth_string)
            conn = TCPConnector(verify_ssl=False)
            async with ClientSession(connector=conn) as session:
                try:
                    url = create_url(auth_url, None, ('token', token))
                    response = await session.post(url, headers={"Authorization": auth_string})
                    res_data = await response.json()
                    result = res_data.get('result')
                    if not result or not res_data.get('loginName'):
                        error_message = res_data.get('errorMsg')
                        logging.info('login_name is invalid, error_message=%s', error_message)
                        redirect_url = create_url(oa_server, oa_logout_api, *url_args)
                        logging.info('redirect to %s', redirect_url)
                        return self.redirect(redirect_url)
                    login_name = res_data['loginName']
                    logging.info('login_name: %s', login_name)
                except Exception as e:
                    logging.exception(e)
                    return self.error('permission denied', status_code=400)
            user = self.save_user(login_name)
            if not user:
                return self.error('permission denied')
            self.session['proxy_user_id'] = str(user.id)
            online_login_limit_toggle = config.get_config('webif.online_login_limit.toggle', False)
            if online_login_limit_toggle and self.session.online_count >= config.get_config("webif.session.online_limit", 10):
                self.session_clear()
                return self.error(ACCOUNT_LOGIN_LIMIT, status_code=400)
            sso_attribute_session_key = config.get_config('mszq_auth.sso_attribute_session_key')
            self.set_cookie(sso_attribute_session_key, token)
            # keep origin url query args
            query = [(arg_k, to_unicode(arg_v[-1])) for arg_k, arg_v in self.request.query_arguments.items()]
            redirect_url = create_url(trident_base, None, *query)
        else:
            redirect_url = create_url(oa_server, oa_login_api, *url_args)
        logging.info('redirect to %s', redirect_url)
        return self.redirect(redirect_url)


@route(r'/mszq/sso-logout')
class MSZQSSOLogoutHandler(BaseHandler):
    def get(self, *args, **kwargs):
        custom_system = self.get_argument('custom_system', '')
        subpath = config.get_config("webif.redirect_subpath", '')
        trident_base = urljoin(self.origin_host, subpath.lstrip('/'))
        if custom_system == 'cas':
            redirect_url = '{}/api/v1/user/cas-logout'.format(trident_base)
        else:
            self.clear_all_cookies()
            self.session_clear()
            oa_server = config.get_config('mszq_auth.oa_server')
            oa_logout_api = config.get_config('mszq_auth.oa_logout_api')
            origin_url = '{}/api/v1/mszq/sso-login'.format(trident_base)

            redirect_url = create_url(oa_server, oa_logout_api, ('targetredirecturl', origin_url))
        logging.debug('Logout, Redirecting to: %s', redirect_url)
        return self.redirect(redirect_url)
