import urllib.parse

from user_proxy import config
from user_proxy.handlers.base import BaseHandler, permission_auth, route
from user_proxy.handlers.forms import SysRequireForm
from user_proxy.models.user import User, RoleType
from user_proxy.utils.util import save_user_excel
from user_proxy.web_services import UserWebService


@route(r'/system/permissions')
class SystemPermissionsHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def get(self, *args, **kwargs):
        res = UserWebService.get_system_permissions(current_user_id=self.current_user.id)
        return self.hand_out_data(res)


@route(r'/roles')
class RolesHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def get(self, *args, **kwargs):
        page, size = self.get_pagination_args()
        business_system_codes = self.get_argument('business_system_codes', '')
        res = UserWebService.get_roles(
            current_user_id=self.current_user.id, page=page, size=size, paginate=self.get_argument('paginate', '1'), business_system_codes=business_system_codes
        )
        return self.hand_out_data(res)

    @permission_auth([User.P_MANAGE])
    def post(self, *args, **kwargs):
        """
        business_segment: "债券业务"
        business_departments: {"department_id": "department_name"}
        business_project_types: {"project_type_id": "project_type_name"}
        :param args:
        :param kwargs:
        :return:
        """
        body = self.get_json_body()
        name = body.get('name')
        permission = body.get('permission')
        oa_default = body.get('oa_default', False)
        super_admin = body.get('super_admin', False)
        business_segment = body.get('business_segment')  # 长江证券业务板块
        business_departments = body.get('business_departments')  # 业务部门信息
        business_project_types = body.get('business_project_types')  # 业务类型信息
        role_type = body.get('role_type')  # 角色类型
        customer_role_name = body.get('customer_role_name', '')  # 自定义角色名称, 权限在配置文件中定义 eg: super_admin/cooperator
        parameter_permission = body.get('parameter_permission')  # 参数提取稽核权限
        res = UserWebService.add_roles(
            current_user_id=self.current_user.id,
            name=name,
            permission=permission,
            oa_default=oa_default,
            super_admin=super_admin,
            business_segment=business_segment,
            business_departments=business_departments,
            business_project_types=business_project_types,
            role_type=role_type,
            customer_role_name=customer_role_name,
            parameter_permission=parameter_permission,
        )
        return self.hand_out_data(res)


@route(r'/roles/(\d+)')
class OperateRoleHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def put(self, role_id, *args, **kwargs):
        body = self.get_json_body()
        name = body.get('name')
        permission = body.get('permission')
        oa_default = body.get('oa_default')
        super_admin = body.get('super_admin')
        business_segment = body.get('business_segment')  # 长江证券业务板块
        business_departments = body.get('business_departments')  # 业务部门信息
        business_project_types = body.get('business_project_types')  # 业务类型信息
        role_type = body.get('role_type')  # 角色类型
        customer_role_name = body.get('customer_role_name', '')  # 自定义角色名称, 权限在配置文件中定义 eg: super_admin/cooperator
        parameter_permission = body.get('parameter_permission')  # 参数提取稽核权限
        if config.get_config('sys') == 'cjsc' and role_type == RoleType.COOPERATOR.value:
            super_admin = False
            business_segment = ''
        res = UserWebService.update_role(
            current_user_id=self.current_user.id,
            name=name,
            permission=permission,
            oa_default=oa_default,
            super_admin=super_admin,
            role_id=role_id,
            business_segment=business_segment,
            business_departments=business_departments,
            business_project_types=business_project_types,
            role_type=role_type,
            customer_role_name=customer_role_name,
            parameter_permission=parameter_permission,
        )
        return self.hand_out_data(res)

    @permission_auth([User.P_MANAGE])
    def get(self, role_id, *args, **kwargs):
        res = UserWebService.get_role_detail(role_id=role_id)
        return self.hand_out_data(res)

    @permission_auth([User.P_MANAGE])
    def delete(self, role_id, *args, **kwargs):
        res = UserWebService.delete_role(current_user_id=self.current_user.id, role_id=role_id)
        return self.hand_out_data(res)


@route(r'/sys-users')
class SysUsersHandler(BaseHandler):
    @permission_auth(token=True)
    def get(self, *args, **kwargs):
        ext_uname = self.get_argument('ext_uname')
        res = UserWebService.get_sys_users(ext_uname=ext_uname)
        return self.hand_out_data(res)


@route(r'/users')
class UsersHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def get(self, *args, **kwargs):
        page = max(int(self.get_argument("page", "1")), 1)
        size = int(self.get_argument("size", "20"))
        res = UserWebService.get_users(current_user_id=self.current_user.id, page=page, size=size)
        return self.hand_out_data(res)

    @permission_auth([User.P_MANAGE])
    def post(self, *args, **kwargs):
        """
        {
            "uid": "a",
            "password": "B",
            "role_ids: [1, 2]
        }
        :param args:
        :param kwargs:
        :return:
        """

        body = self.get_json_body()
        uid = body.get('uid')
        password = body.get('password')
        role_ids = body.get('role_ids', [])
        resign = body.get('resign', False)
        username = body.get('username') or uid
        department = body.get('department')
        work_status = body.get('work_status')
        service_admin = body.get('service_admin')
        group_name = body.get('group_name')
        email = body.get('email')
        allow_login = body.get('allow_login') if config.get_config('sys') == 'ht' else True
        res = UserWebService.add_user(
            current_user_id=self.current_user.id,
            username=username,
            password=password,
            department=department,
            work_status=work_status,
            role_ids=role_ids,
            uid=uid,
            resign=resign,
            service_admin=service_admin,
            group_name=group_name,
            email=email,
            business_system_code=body.get('business_system_code'),
            business_system_name=body.get('business_system_name'),
            department_id=body.get('department_id'),
            phone_number=body.get('phone_number'),
            allow_login=allow_login,
        )
        return self.hand_out_data(res)


@route(r'/users/dump')
class UsersDumpHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def get(self, *args, **kwargs):
        if not config.get_config('webif.feature.dump_user_list', False):
            return self.error('permission denied')
        res = UserWebService.get_all_users(current_user_id=self.current_user.id)
        ret_io = save_user_excel(res, None, ret_raw=True)
        self.set_header('Content-Type', 'application/octet-stream')
        self.set_header('Content-Disposition', 'attachment; filename="%s.xlsx"' % urllib.parse.quote('用户列表'))
        self.write(ret_io.read())
        self.finish()


@route(r'/users/oa')
class UsersOAHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def post(self, *args, **kwargs):
        """
        新增oa用户
        :param args:
        :param kwargs:
        :return:
        """
        body = self.get_json_body()
        uid = body.get('uid')
        role_ids = body.get('role_ids', [])
        res = UserWebService.add_oa_user(uid=uid, role_ids=role_ids)
        return self.hand_out_data(res)


@route(r'/user/change-password')
class UserChangePasswordHandler(BaseHandler):
    @permission_auth()
    def put(self, *args, **kwargs):
        body = self.get_json_body()
        password = body.get('password')
        confirm_password = body.get('confirm_password')
        ignore_passwd_check = config.get_config('sys') == 'gyzq' and not self.current_user.password
        res = UserWebService.update_user_password(
            user_id=self.current_user.id, password=password, confirm_password=confirm_password, ignore_passwd_check=ignore_passwd_check
        )
        self.session.clear_wrong_password_keys(self.current_user.id)
        return self.hand_out_data(res)


@route(r'/user/password')
class UserPasswordHandler(BaseHandler):
    """密码已过期，弹窗修改密码"""

    def put(self, *args, **kwargs):
        body = self.get_json_body()
        uid = body.get('uid')
        password = body.get('password')
        confirm_password = body.get('confirm_password')
        res = UserWebService.update_user_password(user_id=None, password=password, confirm_password=confirm_password, uid=uid)
        self.session.clear_wrong_password_keys(res[1]['id'])
        return self.hand_out_data(res)


@route(r'/users/(\d+)')
class OperateUserHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def put(self, user_id, *args, **kwargs):  # pylint:disable=too-many-locals
        body = self.get_json_body()
        uid = body.get('uid')
        password = body.get('password')
        role_ids = body.get('role_ids', [])
        resign = body.get('resign', None)
        username = body.get('username')
        department = body.get('department')
        work_status = body.get('work_status')
        phone_number = body.get('phone_number')
        department_id = body.get('department_id')
        allow_login = body.get('allow_login')
        service_admin = body.get('service_admin')
        group_name = body.get('group_name')
        email = body.get('email')
        res = UserWebService.update_user(
            current_user_id=self.current_user.id,
            username=username,
            password=password,
            department=department,
            work_status=work_status,
            role_ids=role_ids,
            uid=uid,
            resign=resign,
            user_id=user_id,
            allow_login=allow_login,
            service_admin=service_admin,
            group_name=group_name,
            email=email,
            business_system_code=body.get('business_system_code'),
            business_system_name=body.get('business_system_name'),
            department_id=department_id,
            phone_number=phone_number,
            origin_host=self.origin_host,
        )
        return self.hand_out_data(res)

    @permission_auth([User.P_MANAGE])
    def delete(self, user_id, *args, **kwargs):
        res = UserWebService.delete_user(current_user_id=self.current_user.id, user_id=user_id, origin_host=self.origin_host)
        return self.hand_out_data(res)

    @permission_auth([User.P_MANAGE])
    def get(self, user_id, *args, **kwargs):
        res = UserWebService.get_user(user_id=user_id)
        return self.hand_out_data(res)


@route(r'/users/(\d+)/phone_number')
class OperateUserPhoneNumberHandler(BaseHandler):
    @permission_auth()
    def post(self, user_id, *args, **kwargs):
        body = self.get_json_body()
        phone_number = body.get('phone_number')
        res = UserWebService.operate_user_phone_number(current_user_id=self.current_user.id, phone_number=phone_number)
        return self.hand_out_data(res)


@route(r'/abnormal/users')
class AbnormalUsersHandler(BaseHandler):
    """海通异常用户列表页面"""

    @permission_auth([User.P_MANAGE])
    def get(self, *args, **kwargs):
        page = max(int(self.get_argument("page", "1")), 1)
        size = int(self.get_argument("size", "20"))
        res = UserWebService.get_abnormal_users(page=page, size=size)
        return self.hand_out_data(res)


@route(r'/user/search')
class UserSearchHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def get(self, *args, **kwargs):
        username = self.get_argument('username', '')
        ext_uname = self.get_argument('ext_uname', '')
        department = self.get_argument('department', '')
        business_system_codes = self.get_argument('business_system_codes', '')
        deleted = self.get_argument('deleted', None)
        page, size = self.get_pagination_args()
        res = UserWebService.search_user(
            current_user_id=self.current_user.id,
            ext_uname=ext_uname,
            username=username,
            department=department,
            page=page,
            size=size,
            business_system_codes=business_system_codes,
            deleted=deleted,
        )
        return self.hand_out_data(res)


@route(r'/system/require')
class SystemRequireHandler(BaseHandler):
    @permission_auth()
    def post(self):
        form = SysRequireForm.from_json(self.get_json_body())
        if not form.validate():
            return self.error(self.form_errors_to_str(form.errors))
        res = UserWebService.add_system_require(current_user_id=self.current_user.id, data=form.data)
        return self.hand_out_data(res)


@route(r'/sys-requires')
class SysRequireListHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def get(self):
        sys = self.get_argument('sys', '')
        status = self.get_argument('status', '')
        user_id = self.get_argument('user_id', '')
        user_name = self.get_argument('user_name', '')
        expired = self.get_argument("expired", None)
        page, size = self.get_pagination_args()
        res = UserWebService.get_system_require(sys=sys, status=status, user_id=user_id, user_name=user_name, expired=expired, page=page, size=size)
        return self.hand_out_data(res)


@route(r'/require/(\d+)')
class SysRequireApproveHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def put(self, require_id):
        action = self.get_json_body().get("action", "reject")
        res = UserWebService.update_system_require(require_id=require_id, action=action)
        return self.hand_out_data(res)


@route(r'/customer/sys')
class CustomerSysHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def get(self, *args, **kwargs):
        res = UserWebService.get_customer_sys()
        return self.hand_out_data(res)

    @permission_auth([User.P_MANAGE])
    def post(self, *args, **kwargs):
        body = self.get_json_body()
        sync_user = body.get('sync_user')
        disable_former_employee = body.get('disable_former_employee')
        res = UserWebService.update_customer_sys(sync_user=sync_user, disable_former_employee=disable_former_employee, meta=body)
        return self.hand_out_data(res)
