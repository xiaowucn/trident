# pylint: disable=anomalous-backslash-in-string, too-many-locals, too-many-branches, too-many-branches, too-many-return-statements,too-many-positional-arguments
from copy import deepcopy

from sqlalchemy import true, all_, or_, any_, false
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified

from user_proxy import config
from user_proxy.common.rpc_web_service.common import check_user
from user_proxy.common.rpc_web_service.web_service_base import WebServiceBase
from user_proxy.db import db_session
from user_proxy.handlers.message import (
    INVALID_PARAMETERS,
    ROLE_NAME_DUPLICATE,
    INSUFFICIENT_PERMISSION,
    ROLE_NOT_EXISTS,
    ROLE_CAN_NOT_BE_DELETED,
    USERNAME_DUPLICATE,
    INVALID_OLD_PASSWD,
    USER_NOT_EXISTS,
    USER_CAN_NOT_BE_MODIFIED,
    USER_CAN_NOT_BE_DELETED,
    REQUIRE_NOT_EXISTS,
    USER_EXIST,
    SYNC_USER_ERROR,
    INVALID_USERNAME_OR_PASSWD,
    ACCOUNT_NUMBER_DUPLICATE,
    ROLE_PERMISSION_DUPLICATE,
)
from user_proxy.models.cmbchina import BusinessSystem
from user_proxy.models.criteria import Pagination, ExtFieldsPacker
from user_proxy.models.user import User, Role, SysRequire, RequireStatus, VisitRecord, VisitSys, RoleType, CustomerSysConfig
from user_proxy.utils.authtoken import generate_timestamp
from user_proxy.utils.ht import UpdateUserDataMixin


class UserWebService(WebServiceBase):
    @classmethod
    def get_current_user(cls, user_id, **kwargs):
        user = User.get_by_id(user_id)
        if not user:
            cls.error('用户不存在')

        res = {
            'id': user.id,
            'user_data': user.user_data,
            'ext_uname': user.ext_uname,
            'permissions': user.permissions,
            'resign': user.resign,
            'deleted': user.deleted,
            'created_utc': user.created_utc,
            'updated_utc': user.updated_utc,
            'password': user.password,
            'password_salt': user.password_salt,
            'is_oa': user.is_oa,
            'is_admin': user.is_admin,
            'roles': [
                {
                    'id': role.id,
                    'name': role.name,
                    'permission': role.permission,
                    'created_utc': role.created_utc,
                    'updated_utc': role.updated_utc,
                    'oa_default': role.oa_default,
                    'super_admin': role.super_admin,
                    'role_data': role.role_data,
                }
                for role in user.roles
            ],
        }
        return cls.data(res)

    @classmethod
    def get_user_from_ext_uname(cls, ext_uname, **kwargs):
        user = db_session.query(User).filter(User.ext_uname == ext_uname, User.deleted == 0).first()
        if not user:
            cls.error(INVALID_USERNAME_OR_PASSWD)

        res = {
            'id': user.id,
            'user_data': user.user_data,
            'ext_uname': user.ext_uname,
            'permissions': user.permissions,
            'resign': user.resign,
            'deleted': user.deleted,
            'created_utc': user.created_utc,
            'updated_utc': user.updated_utc,
            'password': user.password,
            'password_salt': user.password_salt,
        }
        return cls.data(res)

    @classmethod
    @check_user
    def get_system_permissions(cls, current_user, **kwargs):
        permission = deepcopy(config.get_config('unify_auth.permission'))
        customer_permission = config.get_config('unify_auth.customer_permission') or {}
        permissions = {
            'permission': permission if not config.get_config('front_config.only_customer_permission') else {},
        }
        autodoc_overall_permissions = permissions['permission'].get('autodoc_overall') or {}
        if current_user.is_swhysc_sponsor_user or current_user.is_swhysc_sponsor_super_admin:
            autodoc_overall_permissions.pop('bond_admin', None)
            customer_permission = {k: v for k, v in customer_permission.items() if k != 'bond_super_admin'}
        elif current_user.is_swhysc_bond_user or current_user.is_swhysc_bond_super_admin:
            autodoc_overall_permissions.pop('sponsor_admin', None)
            customer_permission = {k: v for k, v in customer_permission.items() if k != 'sponsor_super_admin'}
        if autodoc_overall_permissions:
            permissions['permission']['autodoc_overall'] = autodoc_overall_permissions
        permissions['customer_permission'] = customer_permission
        return cls.data(permissions)

    @staticmethod
    def build_get_search_roles_cond(current_user):
        cond = true()
        config_sys = config.get_config('sys')
        if config_sys == 'cjsc':
            if not current_user.is_sys_admin:
                # 业务管理员只能查看默认角色及自己创建的质控角色
                cond &= or_(Role.oa_default.is_(True), Role.role_data.op('->>')('create_user_ext_uname') == current_user.ext_uname)
            else:
                # 系统管理员需过滤管理员角色
                cond &= or_(Role.oa_default.is_(True), Role.role_data.op('->>')('role_type').isnot(None))
        elif config_sys == 'jhzq':
            if current_user.is_sys_admin:
                # 系统管理员只能查看自己创建的业务管理员角色
                cond &= Role.role_data.op('->>')('create_user_id') == str(current_user.id)
            else:
                # 业务管理员只能查看业务管理员创建的角色role_type: 2,3
                cond &= Role.role_data.op('->>')('role_type').in_([str(RoleType.MIDDLE_BACKGROUND.value), str(RoleType.INVESTMENT.value)])
        elif config_sys == 'swhysc':
            # 排除系统初始化的管理员角色
            cond &= ~(Role._permission.op('->>')('autodoc_overall') == ["admin", "normal"])  # pylint: disable=protected-access
            # 角色管理员和用户管理员要分为两个部门, 承销的不能查看固融管理员角色, 固融的不能查看承销保荐管理员角色
            if current_user.is_swhysc_sponsor_user or current_user.is_swhysc_sponsor_super_admin:
                cond &= ~(Role._permission.op('->>')('autodoc_overall') == ["bond_admin"])  # pylint: disable=protected-access
                cond &= or_(Role.role_data.op('->>')('customer_role_name') != 'bond_super_admin', Role.role_data.op('->>')('customer_role_name').is_(None))
            elif current_user.is_swhysc_bond_user or current_user.is_swhysc_bond_super_admin:
                cond &= ~(Role._permission.op('->>')('autodoc_overall') == ["sponsor_admin"])  # pylint: disable=protected-access
                cond &= or_(Role.role_data.op('->>')('customer_role_name') != 'sponsor_super_admin', Role.role_data.op('->>')('customer_role_name').is_(None))
        elif config_sys == 'cmbchina' and not current_user.is_sys_admin:
            cond &= Role.role_data.op('->>')('business_system_code') == (current_user.user_data.get('business_system_code') or '')
        return cond

    @classmethod
    @check_user
    def get_roles(cls, current_user, page, size, **kwargs):
        cond = cls.build_get_search_roles_cond(current_user)
        orderby = []
        if kwargs.get('business_system_codes'):
            cond &= Role.role_data.op('->>')('business_system_code').in_(tuple(kwargs['business_system_codes'].split(',')))
            orderby.append(Role.role_data.op('->>')('business_system_code').desc())
        orderby.append(Role.id.desc())
        query = cls.db.query(Role).filter(cond).order_by(*orderby)
        if kwargs['paginate'] == '0':
            total = query.count()
            return cls.data({"page": 1, "size": total, "total": total, "items": [item.to_dict() for item in query]})
        return cls.data(Pagination(query).limit(page, size).data())

    @staticmethod
    def check_swhysc_operate_role_permission(current_user, permission):
        # 用户管理员无权限
        if current_user.is_swhysc_user_admin:
            return False
        if permission:
            # 角色管理员要分为两个部门, 承销的角色管理员不能操作固融管理员角色, 固融的角色管理员不能操作承销保荐管理员角色
            autodoc_permissions = permission.get('autodoc_overall') or []
            if (current_user.is_swhysc_sponsor_user or current_user.is_swhysc_sponsor_super_admin) and 'bond_admin' in autodoc_permissions:
                return False
            if (current_user.is_swhysc_bond_user or current_user.is_swhysc_bond_super_admin) and 'sponsor_admin' in autodoc_permissions:
                return False
        return True

    @staticmethod
    def check_duplicate_role_permission(current_user, permission):
        business_system_code = current_user.user_data.get('business_system_code')
        if not business_system_code:
            return None
        permission = {key: sorted(value) for key, value in (permission or {}).items() if value}
        # pylint: disable=protected-access
        roles_map = dict(db_session.query(Role.name, Role._permission).filter(Role.role_data.op('->>')('business_system_code') == business_system_code))

        for role_name, role_permission in roles_map.items():
            role_permission = {key: sorted(value) for key, value in (role_permission or {}).items() if value}
            if len(permission) != len(role_permission):
                continue
            if sorted(permission.items()) == sorted(role_permission.items()):
                return role_name
        return None

    @classmethod
    @check_user
    def add_roles(cls, current_user, name, permission, oa_default, super_admin, **kwargs):
        config_sys = config.get_config('sys')
        if config_sys == 'swhysc':
            if not cls.check_swhysc_operate_role_permission(current_user, permission):
                return cls.error(INSUFFICIENT_PERMISSION)
        elif super_admin and not current_user.is_sys_admin and config_sys not in ['citics-tg', 'cmfchina', 'chasing']:
            return cls.error(INSUFFICIENT_PERMISSION)
        if not name or (not permission and config_sys != 'csco'):
            return cls.error(INVALID_PARAMETERS)
        if config_sys == 'cmbchina' and not current_user.is_sys_admin:
            if duplicate_role_name := cls.check_duplicate_role_permission(current_user, permission):
                return cls.error(ROLE_PERMISSION_DUPLICATE.format(duplicate_role_name))
        try:
            if oa_default:
                db_session.query(Role).filter(Role.oa_default.is_(True)).update({Role.oa_default: False})
            role = Role(name=name, oa_default=oa_default)
            role.permission = permission
            role.super_admin = super_admin
            role_data = role.role_data or {}
            if config_sys == 'cjsc':
                role_data['business_segment'] = kwargs.get('business_segment') or ''
                role_data['business_departments'] = kwargs.get('business_departments') or {}
                role_data['business_project_types'] = kwargs.get('business_project_types') or {}
                role_data['create_user_ext_uname'] = current_user.ext_uname
            elif config_sys == 'cmbchina':
                if current_user.user_data.get('business_system_code'):
                    role_data['business_system_code'] = current_user.user_data['business_system_code']
                if current_user.user_data.get('business_system_name'):
                    role_data['business_system_name'] = current_user.user_data['business_system_name']
            role_data['create_user_id'] = current_user.id  # jhzq use trident user, ext_uname can be modified
            if (role_type := kwargs.get('role_type')) is not None:
                role_data['role_type'] = role_type
            if customer_role_name := kwargs.get('customer_role_name'):
                role_data['customer_role_name'] = customer_role_name
            if (parameter_permission := kwargs.get('parameter_permission')) is not None:
                role_data['parameter_permission'] = parameter_permission
            role.role_data = role_data
            flag_modified(role, 'role_data')
            db_session.add(role)
            db_session.commit()
        except IntegrityError:
            return cls.error(ROLE_NAME_DUPLICATE)
        return cls.data(role.to_dict())

    @classmethod
    @check_user
    def update_role(cls, current_user, role_id, name, permission, oa_default, super_admin, **kwargs):
        role = db_session.query(Role).filter(Role.id == role_id).first()
        if not role:
            return cls.error(ROLE_NOT_EXISTS)
        config_sys = config.get_config('sys')
        if config_sys == 'cmbchina':
            if current_user.is_sys_admin:
                if role.role_data.get('create_user_id') != current_user.id:
                    return cls.error(INSUFFICIENT_PERMISSION)
            elif current_user.user_data.get('business_system_code') != role.role_data.get('business_system_code'):
                return cls.error(INSUFFICIENT_PERMISSION)
        if config_sys == 'swhysc':
            if not cls.check_swhysc_operate_role_permission(current_user, role.permission):
                return cls.error(INSUFFICIENT_PERMISSION)
            if not cls.check_swhysc_operate_role_permission(current_user, permission):
                return cls.error(INSUFFICIENT_PERMISSION)
        elif (super_admin or role.super_admin) and not current_user.is_sys_admin and config.get_config('sys') not in ['citics-tg', 'cmfchina', 'chasing']:
            return cls.error(INSUFFICIENT_PERMISSION)
        try:
            if name:
                role.name = name
            if permission is not None:
                role.permission = permission
            if super_admin is not None:
                role.super_admin = super_admin
                for user in role.users:
                    if user.is_sys_admin:
                        continue
                    user_permissions = user.permissions or []
                    if super_admin:
                        if User.P_MANAGE not in user_permissions:
                            user_permissions.append(User.P_MANAGE)
                    else:
                        user_permissions = [user_permission for user_permission in user_permissions if user_permission != User.P_MANAGE]
                    user.permissions = user_permissions
            if oa_default is not None:
                if oa_default:
                    db_session.query(Role).filter(Role.oa_default.is_(True)).update({Role.oa_default: False})
                role.oa_default = oa_default
            else:
                role_data = role.role_data or {}
                if config.get_config('sys') == 'cjsc':
                    role_data['business_segment'] = kwargs.get('business_segment') or ''
                    role_data['business_departments'] = kwargs.get('business_departments') or {}
                    role_data['business_project_types'] = kwargs.get('business_project_types') or {}
                if (role_type := kwargs.get('role_type')) is not None:
                    role_data['role_type'] = role_type
                role_data.pop('customer_role_name', None)
                if customer_role_name := kwargs.get('customer_role_name'):
                    role_data['customer_role_name'] = customer_role_name
                if (parameter_permission := kwargs.get('parameter_permission')) is not None:
                    role_data['parameter_permission'] = parameter_permission
                role.role_data = role_data
                flag_modified(role, 'role_data')
                db_session.commit()
        except IntegrityError:
            return cls.error(ROLE_NAME_DUPLICATE)
        return cls.data(role.to_dict())

    @classmethod
    def get_role_detail(cls, role_id, **kwargs):
        role = db_session.query(Role).filter(Role.id == role_id).first()
        if not role:
            return cls.error(ROLE_NOT_EXISTS)
        return cls.data(role.to_dict())

    @classmethod
    @check_user
    def delete_role(cls, current_user, role_id, **kwargs):
        role = db_session.query(Role).filter(Role.id == role_id).first()
        if not role:
            return cls.error(ROLE_NOT_EXISTS)
        if config.get_config('sys') == 'cmbchina':
            if current_user.is_sys_admin:
                if role.role_data.get('create_user_id') != current_user.id:
                    return cls.error(INSUFFICIENT_PERMISSION)
            elif current_user.user_data.get('business_system_code') != role.role_data.get('business_system_code'):
                return cls.error(INSUFFICIENT_PERMISSION)
        if config.get_config('sys') == 'swhysc':
            if not cls.check_swhysc_operate_role_permission(current_user, role.permission):
                return cls.error(INSUFFICIENT_PERMISSION)
        elif role.super_admin and not current_user.is_sys_admin and config.get_config('sys') not in ['citics-tg', 'cmfchina', 'chasing']:
            return cls.error(INSUFFICIENT_PERMISSION)
        if role.oa_default or role.exist_user_count:
            return cls.error(ROLE_CAN_NOT_BE_DELETED)
        db_session.delete(role)
        db_session.commit()
        return cls.data()

    @classmethod
    def get_sys_users(cls, ext_uname, **kwargs):
        query = db_session.query(User).filter(User.ext_uname == ext_uname, User.deleted == 0).order_by(User.id.desc())
        return cls.data([user.to_dict() for user in query])

    @staticmethod
    def build_get_search_users_cond(current_user, deleted=False):
        config_sys = config.get_config('sys')
        if config_sys == 'cjsc':
            cond = true()
        elif config_sys == 'ht' and deleted:
            # oa异常用户
            cond = (User.deleted != User.USER_STATUS_DEFAULT) & (User.is_oa.is_(True))
        else:
            cond = User.deleted == User.USER_STATUS_DEFAULT
        # 东兴证券用户列表显示sys_admin，非sys_admin不显示用户本身
        if config_sys != 'dxzq' or not current_user.is_sys_admin:
            cond &= User.id != current_user.id
        if config_sys != 'dxzq':
            admin_user_ids = [
                item.id for item in db_session.query(User.id).filter(User.permissions == '{"p_manage"}', User.user_data.op('->>')('ext_sys') == 'self')
            ]
            cond &= User.id.notin_(admin_user_ids)  # 后台创建的admin

        if config_sys == 'cjsc' and not current_user.is_sys_admin:
            department_ids = list(current_user.business_departments.keys())
            cond &= User.user_data.op('->>')('department_id').in_(department_ids)
            cond &= or_(User.permissions.is_(None), 'p_manage' != all_(User.permissions))
        if config_sys == 'jhzq':
            # 只查看业务管理员数据
            if current_user.is_sys_admin:
                cond &= 'p_manage' == any_(User.permissions)
            else:
                # 查看中后台角色、投行条线角色用户数据
                cond &= or_(User.permissions.is_(None), 'p_manage' != all_(User.permissions))
        if config_sys == 'swhysc' and not current_user.is_sys_admin:
            # 用户管理员要分为两个部门, 只能查看所属部门的用户
            dept_id = current_user.user_data.get('department_id')
            sponsor_dept_ids = config.get_config('webif.sponsor_dept_ids') or []
            bond_dept_ids = config.get_config('webif.bond_dept_ids') or []
            if not dept_id:
                cond &= false()
            elif current_user.is_swhysc_sponsor_user or current_user.is_swhysc_sponsor_super_admin:
                cond &= User.user_data.op('->>')('department_id').in_(sponsor_dept_ids)
            elif current_user.is_swhysc_bond_user or current_user.is_swhysc_bond_super_admin:
                cond &= User.user_data.op('->>')('department_id').in_(bond_dept_ids)

        if config_sys == 'citics-tg':
            cond = User.deleted == 0
        if config_sys == 'cmbchina' and not current_user.is_sys_admin and current_user.user_data.get('business_system_code'):
            # 业务管理员只能看到自身业务系统的用户
            cond &= User.user_data.op('->>')('business_system_code') == current_user.user_data['business_system_code']
        if config_sys == 'nesc' and not current_user.is_sys_admin:
            if current_user.user_data.get('customer_department') == 'cw_zq':
                cond &= User.user_data.op('->>')('customer_department') == current_user.user_data['customer_department']
            else:
                cond &= or_(User.user_data.op('->>')('customer_department') != 'cw_zq', User.user_data.op('->>')('customer_department').is_(None))
        return cond

    @classmethod
    def _get_users_query(cls, current_user):
        cond = cls.build_get_search_users_cond(current_user)
        order_by = (User.id.desc(),)
        if config.get_config('sys') == 'kysec':
            order_by = (User.user_data.op('->>')('work_status'),) + order_by
        return db_session.query(User).filter(cond).order_by(*order_by)

    @classmethod
    @check_user
    def get_users(cls, current_user, page, size, **kwargs):
        # 角色管理员无权限
        if current_user.is_swhysc_role_admin:
            return cls.error(INSUFFICIENT_PERMISSION)
        query = cls._get_users_query(current_user)
        return cls.data(Pagination(query).limit(page, size).data())

    @classmethod
    def get_abnormal_users(cls, page, size, **kwargs):
        query = (
            db_session.query(User)
            .filter(
                User.is_oa.is_(True),
                User.deleted != User.USER_STATUS_DEFAULT,
            )
            .order_by(User.process_time.desc(), User.id.desc())
        )
        return cls.data(Pagination(query).limit(page, size).data())

    @classmethod
    @check_user
    def get_all_users(cls, current_user, **kwargs):
        query = cls._get_users_query(current_user)
        return [user.to_dict() for user in query]

    @classmethod
    @check_user
    def search_user(cls, current_user, ext_uname, username, department, page, size, deleted, business_system_codes, **kwargs):
        cond = cls.build_get_search_users_cond(current_user, deleted=deleted)
        name = username or ext_uname
        if config.get_config('sys') == 'cgs' and name:
            cond &= or_(
                User.ext_uname.like("%{}%".format(name.replace('%', '\%'))), User.user_data.op('->>')('username').like("%{}%".format(name.replace('%', '\%')))
            )
        elif ext_uname:
            ext_uname = ext_uname.replace('%', '\%')
            if config.get_config('sys') == 'ht':
                cond &= or_(
                    User.ext_uname.like(f"%{ext_uname}%"),
                    User.user_data.op('->>')('username').like(f"%{ext_uname}%"),
                    User.user_data.op('->>')('uid').like(f"%{ext_uname}%"),
                )
            else:
                cond &= User.ext_uname.like(f"%{ext_uname}%")
        elif username:
            cond &= User.user_data.op('->>')('username').like("%{}%".format(username.replace('%', '\%')))
        if department:
            if config.get_config('sys') == 'kysec':
                cond &= User.user_data.op('->>')('display_department').like("%{}%".format(department.replace('\\', '\\\\').replace('%', '\%')))
            else:
                cond &= User.user_data.op('->>')('department').like("%{}%".format(department.replace('%', '\%')))
        orderby = []
        if business_system_codes:
            cond &= User.user_data.op('->>')('business_system_code').in_(tuple(business_system_codes.split(',')))
            orderby.append(User.user_data.op('->>')('business_system_code').desc())
        if deleted:
            orderby.append(User.process_time.desc())
        orderby.append(User.id.desc())
        query = db_session.query(User).filter(cond).order_by(*orderby)
        return cls.data(Pagination(query).limit(page, size).data())

    @classmethod
    @check_user
    def add_user(cls, current_user, username, password, department, work_status, role_ids, uid, resign, service_admin, allow_login=True, **kwargs):
        _from = 'ht_web' if config.get_config('sys') == 'ht' else 'self'
        data = User.make_user_data(uid, uid, _from=_from, department=department, username=username, allow_login=allow_login, **kwargs)
        if username is not None:
            data['username'] = username
        if department is not None:
            data['department'] = department
        if work_status is not None:
            data['work_status'] = work_status
        if group_name := kwargs.get('group_name'):
            data['group_name'] = group_name
        if email := kwargs.get('email'):
            data['email'] = email
        business_system_code = kwargs.get('business_system_code')
        business_system_name = kwargs.get('business_system_name')
        if config.get_config('sys') == 'cmbchina':
            if not current_user.is_sys_admin and current_user.user_data.get('business_system_code', '') != business_system_code:
                return cls.error(INSUFFICIENT_PERMISSION)
            error_messages = []
            if (
                not business_system_code
                and business_system_name
                and db_session.query(BusinessSystem).filter(BusinessSystem.name == business_system_name).count()
            ):
                error_messages.append('业务系统名称')
            if db_session.query(User).filter(User.ext_uname == uid, User.deleted == 0).count():
                error_messages.append('用户工号')
            if error_messages:
                return cls.error(f"{'、'.join(error_messages)}重复")
            if not business_system_code:
                business_system = BusinessSystem.create(business_system_name)
                business_system_code = business_system.code

            data['business_system_code'] = business_system_code
            data['business_system_name'] = business_system_name
        elif config.get_config('sys') == 'cmfchina' and business_system_code and business_system_code:
            data['business_system_code'] = business_system_code
            data['business_system_name'] = business_system_name
        if not role_ids:
            roles = db_session.query(Role).filter(Role.name == Role.default_name).all()
        else:
            roles = db_session.query(Role).filter(Role.id.in_(role_ids)).all()
        if not uid or not roles:
            return cls.error(INVALID_PARAMETERS)
        if config.get_config('sys') == 'swhysc':
            # 角色管理员无权限
            if current_user.is_swhysc_role_admin:
                return cls.error(INSUFFICIENT_PERMISSION)
            if current_user.is_swhysc_user_admin or current_user.is_swhysc_sponsor_super_admin or current_user.is_swhysc_bond_super_admin:
                data['department_id'] = current_user.user_data.get('department_id')
        elif any(role.super_admin for role in roles) and not current_user.is_sys_admin and config.get_config('sys') not in ['citics-tg', 'cmfchina', 'chasing']:
            return cls.error(INSUFFICIENT_PERMISSION)
        try:
            deleted_user = db_session.query(User).filter(User.ext_uname == uid, User.deleted == 1).first()
            user = User.make_user_from_password(uid, password, roles, user=deleted_user, resign=resign, user_data=data, service_admin=service_admin)
        except IntegrityError:
            # db_session.rollback()
            return cls.error(USERNAME_DUPLICATE if config.get_config('sys') not in ['swhysc', 'citics-tg'] else ACCOUNT_NUMBER_DUPLICATE)
        if config.get_config('webif.feature.stat_user_operation', False):
            record_data = {'action_message': f'新增用户，ID为{user.id}', 'action_type': '新增'}
            VisitRecord.create(current_user.id, VisitSys.USER_MANAGE.value, record_data=record_data)
        return cls.data(user.to_dict())

    @classmethod
    def update_user_password(cls, password, user_id, confirm_password, **kwargs):
        if kwargs.get('uid'):
            cond = User.ext_uname == kwargs['uid']
        else:
            cond = User.id == user_id
        user = db_session.query(User).filter(cond).first()
        if not user:
            return cls.error('no such user')
        ignore_passwd_check = kwargs.get('ignore_passwd_check')
        if not password or (not ignore_passwd_check and not confirm_password):
            return cls.error(INVALID_PARAMETERS)
        if not ignore_passwd_check and not user.check_password(confirm_password):
            return cls.error(INVALID_OLD_PASSWD)
        user.set_password(password)
        if config.get_config('webif.feature.check_admin_password_expired.enable', False) and user.is_sys_admin:
            expired_time = config.get_config('webif.feature.check_admin_password_expired.expire_seconds', 90 * 60 * 60 * 24)
            user.user_data['password_expired_time'] = generate_timestamp() + expired_time
            flag_modified(user, 'user_data')
        db_session.commit()
        return cls.data(user.to_dict())

    @classmethod
    @check_user
    def update_user(cls, current_user, user_id, uid, password, role_ids, resign, username, department, work_status, allow_login, service_admin, **kwargs):
        if user_id == current_user.id and config.get_config('sys') != 'citics-tg':
            return cls.error(USER_CAN_NOT_BE_MODIFIED)
        user = db_session.query(User).filter(User.id == user_id).first()
        if (
            config.get_config('sys') == 'cmbchina'
            and not current_user.is_sys_admin
            and user
            and user.user_data.get('business_system_code', '') != current_user.user_data.get('business_system_code', '')
        ):
            return cls.error(INSUFFICIENT_PERMISSION)
        if not user:
            return cls.error(USER_NOT_EXISTS)
        stat_user_operation = config.get_config('webif.feature.stat_user_operation', False)
        try:
            if uid is not None and uid != user.ext_uname and not user.oa_user:
                if config.get_config('sys') == 'ht' and not UpdateUserDataMixin.delete_autodoc_user(kwargs['origin_host'], user):
                    return cls.error(SYNC_USER_ERROR)
                if stat_user_operation:
                    record_data = {'action_message': f'ID{user.id}用户，用户名已修改，由“{user.ext_uname}”修改为“{uid}”', 'action_type': '修改'}
                    VisitRecord.create(current_user.id, VisitSys.USER_MANAGE.value, record_data=record_data)
                user.ext_uname = uid
                user.user_data.update(
                    {
                        'uid': uid,
                        'ext_uname': uid,
                        'username': username if username else uid,
                    }
                )
                flag_modified(user, 'user_data')
            if password is not None and (not user.oa_user or config.get_config('front_config.allow_change_password')):
                if stat_user_operation:
                    record_data = {'action_message': f'ID{user.id}用户，密码已修改', 'action_type': '修改'}
                    VisitRecord.create(current_user.id, VisitSys.USER_MANAGE.value, record_data=record_data)
                user.set_password(password)
            if role_ids:
                roles = db_session.query(Role).filter(Role.id.in_(role_ids)).all()
                if roles != user.roles:
                    if stat_user_operation:
                        origin_role_name = ''.join([item.name for item in user.roles])
                        role_name = ''.join([item.name for item in roles])
                        record_data = {'action_message': f'ID{user.id}用户，角色已修改，由“{origin_role_name}”修改为“{role_name}”', 'action_type': '修改'}
                        VisitRecord.create(current_user.id, VisitSys.USER_MANAGE.value, record_data=record_data)
                    user.roles = roles
                    user.user_data.update({'roles_modify': True})
                    flag_modified(user, 'user_data')

                    user_permissions = user.permissions or []
                    if any(role.super_admin for role in roles):
                        if config.get_config('sys') == 'swhysc':
                            # 角色管理员无权限
                            if current_user.is_swhysc_role_admin:
                                return cls.error(INSUFFICIENT_PERMISSION)
                        elif not current_user.is_sys_admin and config.get_config('sys') not in ['citics-tg', 'cmfchina', 'chasing']:
                            return cls.error(INSUFFICIENT_PERMISSION)
                        if User.P_MANAGE not in user_permissions:
                            user_permissions.append(User.P_MANAGE)
                    else:
                        user_permissions = [user_permission for user_permission in user_permissions if user_permission != User.P_MANAGE]
                    user.permissions = user_permissions
            if resign is not None:
                user.resign = resign

            if config.get_config('sys') == 'xyzq' and service_admin is not None:
                user_permissions = user.permissions or []
                action_message = ''
                if service_admin:
                    if User.P_MANAGE not in user_permissions:
                        user_permissions.append(User.P_MANAGE)
                        action_message = f'ID{user.id}用户，业务管理员角色已修改，用户管理可见'
                else:
                    if User.P_MANAGE in user_permissions:
                        action_message = f'ID{user.id}用户，业务管理员角色已修改，用户管理不可见'
                    user_permissions = [user_permission for user_permission in user_permissions if user_permission != User.P_MANAGE]
                user.permissions = user_permissions
                if action_message:
                    record_data = {'action_message': action_message, 'action_type': '修改'}
                    VisitRecord.create(current_user.id, VisitSys.USER_MANAGE.value, record_data=record_data)

            data = {}
            if username is not None:
                data['username'] = username
            if department is not None:
                data['department'] = department
            if work_status is not None:
                data['work_status'] = work_status
            if kwargs.get('phone_number') is not None:
                data['phone_number'] = kwargs['phone_number']
            if kwargs.get('department_id'):
                data['department_id'] = kwargs['department_id']
            if allow_login is not None:
                data['allow_login'] = allow_login
                if config.get_config('sys') == 'guosen':
                    data['ustatus'] = '0' if allow_login else '1'
                if config.get_config('sys') == 'ht':
                    user.process_time = generate_timestamp()
                    # 异常用户被管理员设为允许登录，状态更新为正常用户
                    if allow_login and user.deleted == User.HT_USER_STATUS_ABNORMAL:
                        user.deleted = User.USER_STATUS_DEFAULT
            if group_name := kwargs.get('group_name'):
                data['group_name'] = group_name
            if email := kwargs.get('email'):
                data['email'] = email
            if kwargs.get('business_system_code'):
                data['business_system_code'] = kwargs['business_system_code']
            if kwargs.get('business_system_name'):
                data['business_system_name'] = kwargs['business_system_name']
            if data:
                user.user_data.update(data)
                flag_modified(user, 'user_data')
            db_session.commit()
        except IntegrityError:
            return cls.error(USERNAME_DUPLICATE)
        return cls.data(user.to_dict())

    @classmethod
    @check_user
    def operate_user_phone_number(cls, current_user, phone_number, **kwargs):

        if not phone_number:
            return cls.error(INVALID_PARAMETERS)
        current_user.user_data["phone_number"] = phone_number
        flag_modified(current_user, 'user_data')
        db_session.commit()
        return cls.data(current_user.to_dict())

    @classmethod
    @check_user
    def delete_user(cls, current_user, user_id, origin_host, **kwargs):
        # 角色管理员无权限
        if current_user.is_swhysc_role_admin:
            return cls.error(INSUFFICIENT_PERMISSION)
        if user_id == current_user.id:
            return cls.error(USER_CAN_NOT_BE_DELETED)
        config_sys = config.get_config('sys')
        cond = User.id == user_id
        user = db_session.query(User).filter(cond).first()
        if user.oa_user:
            return cls.error(USER_CAN_NOT_BE_DELETED)
        if (
            config.get_config('sys') == 'cmbchina'
            and not current_user.is_sys_admin
            and user
            and user.user_data.get('business_system_code', '') != current_user.user_data.get('business_system_code', '')
        ):
            return cls.error(INSUFFICIENT_PERMISSION)
        if not user:
            return cls.error(USER_NOT_EXISTS)
        if user.is_sys_admin:
            return cls.error(USER_CAN_NOT_BE_DELETED)
        if config_sys == 'ht' and not user.is_oa and not UpdateUserDataMixin.delete_autodoc_user(origin_host, user):
            return cls.error(SYNC_USER_ERROR)
        user.deleted = User.USER_STATUS_DELETED
        user.process_time = generate_timestamp()
        if config.get_config('webif.feature.stat_user_operation', False):
            record_data = {'action_message': f'删除用户，ID为{user.id}', 'action_type': '删除'}
            VisitRecord.create(current_user.id, VisitSys.USER_MANAGE.value, record_data=record_data)
        db_session.commit()
        return cls.data(None)

    @classmethod
    def get_user(cls, user_id, **kwargs):
        user = db_session.query(User).filter(User.id == user_id).first()
        if not user:
            return cls.error(USER_NOT_EXISTS)
        return cls.data(user.to_dict())

    @classmethod
    @check_user
    def add_system_require(cls, current_user, data, **kwargs):
        lock = db_session.query(User.id).with_for_update().filter_by(id=current_user.id).one()
        current_require = current_user.required_sys.filter(
            SysRequire.end_utc > generate_timestamp(), SysRequire.sys == data["sys"], SysRequire.status != RequireStatus.reject.value
        ).first()
        if current_require:
            return cls.error("您已申请该项目")

        require = SysRequire(user_id=current_user.id, **data)
        db_session.add(require)
        db_session.commit()
        return cls.data(require.to_dict())

    @classmethod
    def get_system_require(cls, sys, status, user_id, user_name, expired, page, size, **kwargs):
        cond = true()
        if sys:
            cond &= SysRequire.sys == sys
        if status in RequireStatus.names():
            cond &= SysRequire.status == RequireStatus[status].value
        if user_id:
            cond &= SysRequire.user_id == user_id
        elif user_name:
            user_query = db_session.query(User.id).filter(User.ext_uname.like("%{}%".format(user_name.replace('%', '\%'))), User.deleted == 0).subquery()
            cond &= SysRequire.user_id.in_(user_query)
        if expired is not None:
            if expired == "1":
                cond &= SysRequire.end_utc <= generate_timestamp()
            else:
                cond &= SysRequire.end_utc > generate_timestamp()

        query = db_session.query(SysRequire, User.ext_uname).outerjoin(User).filter(cond).order_by(SysRequire.id.desc())
        packer = ExtFieldsPacker(["ext_uname"], defaults={"ext_uname": ""})
        return cls.data(Pagination(query, packer=packer).limit(page, size).data())

    @classmethod
    def get_customer_sys(cls):
        customer_sys = db_session.query(CustomerSysConfig).first()
        return cls.data(customer_sys.to_dict())

    @classmethod
    def update_customer_sys(cls, sync_user=None, disable_former_employee=None, meta=None):
        customer_sys = db_session.query(CustomerSysConfig).first()
        if sync_user is not None:
            customer_sys.sync_user = sync_user
        if disable_former_employee is not None:
            customer_sys.disable_former_employee = disable_former_employee
        if meta is not None:
            customer_sys_meta = customer_sys.meta or {}
            customer_sys_meta.update(meta)
            customer_sys.meta = customer_sys_meta
            flag_modified(customer_sys, 'meta')
        db_session.commit()
        return cls.data(customer_sys.to_dict())

    @classmethod
    def update_system_require(cls, require_id, action, **kwargs):
        require = db_session.query(SysRequire).filter(SysRequire.id == require_id).first()
        if not require:
            return cls.error(REQUIRE_NOT_EXISTS)
        require.status = RequireStatus.approved.value if action == "approve" else RequireStatus.reject.value
        db_session.commit()
        return cls.data(require.to_dict())

    @classmethod
    def add_oa_user(cls, uid, role_ids, **kwargs):
        roles = db_session.query(Role).filter(Role.id.in_(role_ids)).all()
        if not uid or not roles:
            return cls.error(INVALID_PARAMETERS)
        user = db_session.query(User).filter(User.ext_uname == uid, User.deleted == 0).first()
        if user:
            return cls.error(USER_EXIST)
        try:
            deleted_user = db_session.query(User).filter(User.ext_uname == uid, User.deleted == 1).first()
            user = User.make_oa_user(uid, roles, user=deleted_user, user_data={})
        except IntegrityError:
            # db_session.rollback()
            return cls.error(USERNAME_DUPLICATE)
        return cls.data(user.to_dict())
