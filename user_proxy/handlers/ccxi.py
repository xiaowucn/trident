import logging

from user_proxy import config
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.utils.cas import create_cas_login_url, validate, create_url


@route(r'/ccxi/cas-login')
class CCXICasHandler(BaseHandler):
    @staticmethod
    def save_user(cas_res):
        uid = cas_res['cas:attributes']['cas:id']
        ext_uname = cas_res['cas:user']
        user = User.make_user(uid=uid, ext_uname=ext_uname)
        return user

    def get(self, *args, **kwargs):
        cas_token_session_key = config.get_config('cas_auth.cas_token_session_key')
        ticket = self.get_argument(cas_token_session_key, None)
        base_url = self.origin_host
        origin_url = '{}/api/v1/ccxi/cas-login'.format(base_url)
        query = (('sys', self.get_argument('sys', 'scriber')), ('redirect', self.get_argument('redirect', None)))
        origin_url = create_url(origin_url, None, *query)
        if ticket:
            status, data = validate(ticket, origin_url, self)
            if status:
                user = self.save_user(data)
                if not user:
                    return self.error('permission denied')
                self.session['proxy_user_id'] = str(user.id)
                redirect_url = create_url(self.origin_host, config.get_config('cas_auth.cas_after_login'), *query)
            else:
                return self.error('permission denied')
        else:
            redirect_url = create_cas_login_url(
                config.get_config('cas_auth.server'),
                config.get_config('cas_auth.login_uri'),
                origin_url
            )

        logging.debug('Redirecting to: {0}'.format(redirect_url))
        return self.redirect(redirect_url)
