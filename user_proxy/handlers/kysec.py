import os
from io import BytesIO

from user_proxy import config
from user_proxy.handlers.base import route, BaseHandler, permission_auth
from user_proxy.handlers.message import FILE_DOES_NOT_SUPPORT
from user_proxy.models.user import User
from user_proxy.utils.kysec import parse_user_list_from_excel
from user_proxy.utils.ldap import ldap_login, login_precheck


@route(r'/kysec/use-list')
class UserListHandler(BaseHandler):
    @permission_auth()
    def post(self, *args, **kwargs):
        file1 = self.request.files['file'][0]
        original_fname = os.path.basename(file1['filename'].replace("\\", "/"))
        file_ext = os.path.splitext(original_fname)[1].lower()
        if file_ext.lower() != '.xlsx':
            return self.error(FILE_DOES_NOT_SUPPORT)
        file_content = file1['body']
        file_data = BytesIO()
        file_data.write(file_content)
        file_data.seek(0)
        parse_user_list_from_excel(file_data)
        return self.data(None)


@route(r'/kysec/sso-login')
class KysecSSOLoginHandler(BaseHandler):
    def post(self, *args, **kwargs):
        uid = self.get_argument('uid')
        password = self.get_argument('password')

        if not login_precheck(uid):
            return self.redirect('/')
        status, ret_val = ldap_login(uid, password)
        if not status:
            return self.error(ret_val)
        # ret_val = '1', [2, '2', '3']
        # 创建本地用户
        # user_dn, attrlist = ret_val
        # department_id, department, username = [item.decode('utf-8') if item is not None else item for item in attrlist]

        user = User.make_user(
            uid=uid, ext_uname=uid
        )
        if not user:
            return self.redirect('/')
        work_status = user.user_data.get('work_status', '')
        if work_status != User.STATUS_OFFICILA:
            return self.redirect('/')
        after_login = config.get_config('ldap.after_login', '')
        url = self.gen_redirect_url(after_login)
        self.session['proxy_user_id'] = str(user.id)
        return self.redirect(url)
