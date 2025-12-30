from urllib.parse import urljoin

from user_proxy import config
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User
from user_proxy.utils.hash import md5sum


@route(r'/szse/get-off')
class SZSEGetOffHandler(BaseHandler):
    def get(self, *args, **kwargs):
        system = self.get_argument('redirectUrl')
        username = self.get_argument('username')
        token = self.get_argument('token')
        origin = self.get_argument('origin', None)
        project_group_id = self.get_argument('project_group_id', None)

        if token != md5sum('szse:username={}'.format(username)):
            return self.error('permission denied', status_code=400)

        user = User.make_user(username, username, username=username, _from='szse')
        self.session['proxy_user_id'] = str(user.id)
        subpath = config.get_config('webif.redirect_subpath', '')
        base_url = urljoin(self.origin_host, subpath.lstrip('/'))
        return self.redirect(urljoin(base_url, 'api/v1/get-off?sys={}&origin={}&project_group_id={}'.format(system, origin or '', project_group_id or '')))
