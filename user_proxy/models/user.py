# pylint:disable=too-many-return-statements,too-many-positional-arguments,too-many-locals,too-many-branches
import copy
import hashlib
import uuid
from copy import deepcopy
from enum import IntEnum, Enum, unique

from sqlalchemy import Boolean, Column, ForeignKey, String, Table, or_
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import relationship, aliased
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.types import Integer

from user_proxy import config
from user_proxy.db import BaseModel, db_session
from user_proxy.utils.authtoken import generate_timestamp

user_role_mapping = Table(
    'user_role_mapping', BaseModel.metadata, Column('user_id', Integer, ForeignKey('user.id')), Column('role_id', Integer, ForeignKey('roles.id'))
)


class RoleType(IntEnum):
    OTHER = -1  # 其他
    SUPER_ADMIN = 0  # 业务管理员
    COOPERATOR = 1  # 质控
    MIDDLE_BACKGROUND = 2  # 中后台角色
    INVESTMENT = 3  # 投行角色


class Role(BaseModel):
    __tablename__ = 'roles'

    default_name = '默认角色'  # 普通用户
    vip_user = u'vip'  # vip用户
    manager = '管理员'

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    _permission = Column('permission', JSONB)
    oa_default = Column(Boolean, default=False)
    super_admin = Column(Boolean, default=False)
    role_data = Column(JSONB, default={})
    created_utc = Column(Integer, default=generate_timestamp)
    updated_utc = Column(Integer, default=generate_timestamp, onupdate=generate_timestamp)

    users = relationship(
        "User",
        secondary=user_role_mapping,
        back_populates="roles",
        lazy="dynamic",
    )

    @property
    def exist_user_count(self):
        return self.users.filter(User.deleted == 0).count()

    @staticmethod
    def ensure_sub_permission(sub_permissions):
        if 'admin' in sub_permissions:
            return ['admin']
        elif 'dep_admin' in sub_permissions:
            return ['dep_admin']
        return sub_permissions

    def is_init_roles(self):
        return self.name in config.get_config('unify_auth.init_role_names', ['管理员', '默认角色'])

    @property
    def permission(self):
        # 将role中所有子权限没有在配置文件中的删掉
        permission = deepcopy(self._permission)
        sys_permission = config.get_config('unify_auth.permission') or {}
        for sys, sub_permissions in permission.items():
            sys_sub_permission = sys_permission.get(sys, {})
            deleted_sub_permissions = set(sub_permissions) - set(sys_sub_permission.keys())
            for deleted_sub_permission in deleted_sub_permissions:
                sub_permissions.remove(deleted_sub_permission)
            permission[sys] = self.ensure_sub_permission(sub_permissions) if config.get_config('sys') != 'cmbchina' else sub_permissions
        # scriber 中的table_identification与PDFlux中的normal权限绑定
        if 'scriber' in permission and 'table_identification' in permission['scriber']:
            permission['pdflux'] = ['normal']

        # 没有角色管理界面的环境，新增子系统，默认角色和管理员角色中填充permission
        if not config.get_config('unify_auth.show_role_manage', True) and self.is_init_roles():
            simple_permissions = config.get_config('unify_auth.sub_sys_simple_permissions', {})
            for sys, simple_permission in simple_permissions.items():
                if sys not in permission:
                    add_permission = simple_permission.get('oa_default') if self.oa_default else simple_permission.get('admin')
                    if add_permission:
                        permission[sys] = add_permission
        elif (customer_permission := config.get_config('unify_auth.customer_permission')) and (
            customer_role_name := (self.role_data or {}).get('customer_role_name')
        ):
            if customer_role_name in customer_permission:
                return customer_permission[customer_role_name]
        return permission

    @permission.setter
    def permission(self, _permission):
        self._permission = _permission

    @classmethod
    def create_tmp_ins(cls, data):
        new_ist = cls()
        for key, val in data.items():
            setattr(new_ist, key, val)
        return new_ist

    def to_dict(self):
        sys_permissions = config.get_config('unify_auth.permission') or {}
        permissions = {}
        for permission_name, value in self.permission.items():
            if permission_name in sys_permissions:
                permissions[permission_name] = value
        role_data = copy.deepcopy(self.role_data or {})
        if config.get_config('sys') == 'cmbchina':
            if user_id := role_data.get('create_user_id'):
                user = db_session.query(User).filter(User.id == user_id).first()
                if user:
                    role_data['create_user_name'] = user.user_data.get('username')
        return {
            'id': self.id,
            'name': self.name,
            'permission': permissions,
            'created_utc': self.created_utc,
            'updated_utc': self.updated_utc,
            'oa_default': self.oa_default,
            'user_count': self.exist_user_count,
            'super_admin': self.super_admin,
            'role_data': role_data,
        }

    def __repr__(self):
        return "<Role: {} {}>".format(self.id, self.name)


class RequireStatus(IntEnum):
    # pylint: disable=invalid-name
    default = 0
    approved = 1
    reject = -1

    @classmethod
    def names(cls):
        return [item.name for item in cls]


@unique
class UserStatus(Enum):
    # pylint: disable=invalid-name
    default = 0
    deleted = 1
    abnormal = 2


class User(BaseModel):
    __tablename__ = 'user'

    P_MANAGE = 'p_manage'

    STATUS_OFFICILA = 1
    STATUS_RESIGN = 2
    STATUS_RETIREMENT = 3

    XYZQ_STATUS_VALIDATION = '1'  # 兴业证券在职用户

    EXT_SYS_WECHAT = 'wx'
    EXT_SYS_VIP = 'vip'

    KYSEC_USER_STATUS_MAP = {
        STATUS_OFFICILA: '在职',
        STATUS_RESIGN: '离职',
        STATUS_RETIREMENT: '退休',
    }
    EBSCN_USER_VALID_STATUS_MAP = {
        '0': '试用',
        '1': '正式',
        '2': '临时',
        '3': '试用延期',
        # '4': '解聘',
        # '5': '离职',
        # '6': '退休',
        # '7': '无效'
    }

    OA_NOT_UPDATE_FIELDS = ['phone_number', 'allow_login']
    DEP_ADMIN_KEY = 'dep_admin'

    USER_STATUS_DEFAULT = UserStatus.default.value  # 默认正常状态
    USER_STATUS_DELETED = UserStatus.deleted.value  # 删除状态
    HT_USER_STATUS_ABNORMAL = UserStatus.abnormal.value  # 海通同步异常状态

    id = Column(Integer, primary_key=True)
    ext_uname = Column(String)
    user_data = Column(JSONB)
    password = Column(String)
    password_salt = Column(String)
    session_id = Column(String)
    resign = Column(Boolean, default=False)
    permissions = Column(ARRAY(String))
    deleted = Column(Integer, default=0)
    created_utc = Column(Integer, default=generate_timestamp)
    updated_utc = Column(Integer, default=generate_timestamp, onupdate=generate_timestamp)
    process_time = Column(Integer, default=generate_timestamp)
    is_oa = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    department_id = Column(Integer, ForeignKey("departments.id"))

    visit_records = relationship("VisitRecord", back_populates="user", lazy="dynamic")
    roles = relationship("Role", secondary=user_role_mapping, lazy="joined")

    required_sys = relationship("SysRequire", lazy="dynamic", back_populates="user")

    department = relationship("Department", back_populates="users", uselist=False)
    ldap_user_record = relationship("LDAPUserRecord", back_populates="user")

    @property
    def oa_user(self):
        if self.user_data.get('_from') == 'cas':
            return True
        if '_from' not in self.user_data and self.user_data.get('ext_sys') != 'self':
            return True
        if self.user_data.get('_from') and self.user_data['_from'] != 'self':
            return True
        return False

    @property
    def is_sys_admin(self):
        if not self.permissions or self.user_data.get('ext_sys') != 'self':
            return False
        return any(permission == self.P_MANAGE for permission in self.permissions)

    @property
    def is_swhysc_user_admin(self):
        if config.get_config('sys') != 'swhysc':
            return False
        return any((role.role_data or {}).get('customer_role_name') == 'user_admin' for role in self.roles)

    @property
    def is_swhysc_sponsor_super_admin(self):
        if config.get_config('sys') != 'swhysc':
            return False
        return any((role.role_data or {}).get('customer_role_name') == 'sponsor_super_admin' for role in self.roles)

    @property
    def is_swhysc_bond_super_admin(self):
        if config.get_config('sys') != 'swhysc':
            return False
        return any((role.role_data or {}).get('customer_role_name') == 'bond_super_admin' for role in self.roles)

    @property
    def is_swhysc_sponsor_user(self):
        if config.get_config('sys') != 'swhysc':
            return False
        sponsor_dept_ids = config.get_config('webif.sponsor_dept_ids') or []
        return self.user_data.get('department_id') in sponsor_dept_ids

    @property
    def is_swhysc_bond_user(self):
        if config.get_config('sys') != 'swhysc':
            return False
        bond_dept_ids = config.get_config('webif.bond_dept_ids') or []
        return self.user_data.get('department_id') in bond_dept_ids

    @property
    def is_swhysc_role_admin(self):
        if config.get_config('sys') != 'swhysc':
            return False
        return any((role.role_data or {}).get('customer_role_name') == 'role_admin' for role in self.roles)

    @property
    def is_super_admin(self):
        return any(role.super_admin for role in self.roles)

    @property
    def is_dep_admin(self):
        return (self.user_data or {}).get(self.DEP_ADMIN_KEY) is True

    @property
    def department_info(self):
        user_data = self.user_data or {}
        return {
            'department': user_data.get('department'),
            'department_id': user_data.get('department_id'),
        }

    @property
    def business_segment(self):
        if config.get_config('sys') != 'cjsc':
            return ''
        for role in self.roles:
            _business_segment = (role.role_data or {}).get('business_segment')
            if _business_segment:
                return _business_segment
        return ''

    @property
    def business_departments(self):
        _business_departments = {}
        if config.get_config('sys') != 'cjsc':
            return _business_departments
        for role in self.roles:
            item = (role.role_data or {}).get('business_departments')
            if item:
                _business_departments.update(item)
        return _business_departments

    @property
    def business_project_types(self):
        _business_project_types = {}
        if config.get_config('sys') != 'cjsc':
            return _business_project_types
        for role in self.roles:
            item = (role.role_data or {}).get('business_project_types')
            if item:
                _business_project_types.update(item)
        return _business_project_types

    @property
    def allow_login(self):
        if self.deleted == User.USER_STATUS_DELETED:
            return False
        if config.get_config('sys') == 'stocke':
            if self.is_sys_admin:
                return True
            # 禁用用户
            if self.user_data.get('work_status') == 2:
                return False
            return self.user_data.get('allow_login', False)
        if self.user_data.get('allow_login') is False:
            return False
        if self.deleted != User.USER_STATUS_DEFAULT and self.user_data.get('expired_time') and generate_timestamp() > self.user_data['expired_time']:
            return False
        return True

    def check_password(self, password):
        if not self.password:
            return False
        password = hashlib.md5("{}{}".format(password, self.password_salt).encode()).hexdigest()
        return self.password == password

    def set_password(self, password):
        if not password:
            return
        self.password_salt = hashlib.md5(uuid.uuid4().hex.encode()).hexdigest()
        self.password = hashlib.md5("{}{}".format(password, self.password_salt).encode()).hexdigest()

    @classmethod
    def make_user_from_password(cls, uid, password, roles, user=None, resign=False, user_data=None, service_admin=None):
        if user is None:
            user = User()
        user.ext_uname = uid
        user.set_password(password)
        user.user_data = {'uid': uid, 'ext_uname': uid, 'ext_sys': config.get_config('sys'), 'username': uid, '_from': 'self', 'source': 'trident'}
        if user_data:
            user.user_data.update(user_data)
            flag_modified(user, 'user_data')
        permissions = []
        if any(role.super_admin for role in roles) or service_admin:
            permissions.append(cls.P_MANAGE)
        user.permissions = permissions
        user.roles = roles
        user.resign = resign
        user.is_oa = False
        user.deleted = 0
        db_session.add(user)
        db_session.commit()
        return user

    @classmethod
    def make_oa_user(cls, uid, roles, user=None, resign=False, user_data=None):
        if not user:
            user = User()
        user.ext_uname = uid
        user.user_data = {'uid': uid, 'ext_uname': uid, 'ext_sys': config.get_config('sys'), 'username': uid, '_from': config.get_config('sys')}
        if user_data:
            user.user_data.update(user_data)
            flag_modified(user, 'user_data')
        permissions = []
        if any(role.super_admin for role in roles):
            permissions.append(cls.P_MANAGE)
        user.permissions = permissions
        user.roles = roles
        user.resign = resign
        user.deleted = 0
        user.is_oa = True
        db_session.add(user)
        db_session.commit()
        return user

    @classmethod
    def make_user_data(cls, uid, ext_uname, _from=None, department=None, department_id=None, username=None, phone_number=None, allow_login=None, **options):
        return {
            'uid': uid,
            'ext_uname': ext_uname,
            'ext_sys': config.get_config('sys'),
            'department': department,
            'department_id': department_id,
            'username': username,
            'phone_number': phone_number,
            '_from': _from if _from is not None else config.get_config('sys'),
            'allow_login': allow_login,
            **options,
        }

    @classmethod
    def make_user(
        cls, uid, ext_uname, _from=None, department=None, department_id=None, username=None, is_oa=True, password=None, department_ins=None, **options
    ):
        if config.get_config('sys') == 'ht':
            if options.get('is_sync'):
                # 海通同步用户ext_uname是uid，需要根据uid查询
                user = db_session.query(cls).filter((cls.user_data.op('->>')('uid') == uid), cls.ext_uname != username, cls.is_oa.is_(True)).first()
                if user:
                    ext_uname = user.ext_uname
            else:
                user = db_session.query(cls).filter(cls.ext_uname == ext_uname, cls.is_oa == is_oa).first()
        elif _from == 'casdoor' and options.get('uuid'):
            user = db_session.query(cls).filter(or_(cls.ext_uname == ext_uname, cls.user_data.op('->>')('uuid') == options['uuid'])).first()
        else:
            user = db_session.query(cls).filter(cls.ext_uname == ext_uname).first()
        user_data = cls.make_user_data(uid, ext_uname, _from, department, department_id, username, **options)
        update_flag = True
        if not user:
            if config.get_config('unify_auth.auto_create_user', True):
                user = cls()
                user.user_data = user_data
                role = db_session.query(Role).filter(Role.oa_default.is_(True)).first()
                if not role:
                    return None
                user.roles = [role]
                user.ext_uname = ext_uname
            else:
                return None
        else:
            if user.is_sys_admin:
                return user
            if user.deleted:
                user.deleted = 0
                # 删除的用户应该赋予默认权限
                role = db_session.query(Role).filter(Role.oa_default.is_(True)).first()
                if not role:
                    return None
                user.roles = [role]
                user.permissions = []
            if config.get_config('sys') == 'ht':
                # 已有二级用户的部门及配置信息更新需根据一级部门是否改变
                department_org_id = user.user_data.get('department_id')
                if department_org_id and options.get('is_sync'):
                    department_org = db_session.query(Department).filter(Department.external_id == department_org_id, Department.deleted == 0).first()
                    if department_org and department_org.department_type == Department.HT_SECONDARY_SECTOR:
                        parent_department = (
                            db_session.query(Department).filter(Department.external_id == department_org.parent_id, Department.deleted == 0).first()
                        )
                        if parent_department and parent_department.external_id == department_id:
                            # 一级部门不变, 不更新部门信息
                            update_flag = False
                            user_data.pop('department', '')
                            user_data.pop('department_id', '')
                        else:
                            # 需删除autodoc_data信息后更新
                            user_data.pop('autodoc_data', {})

                user.user_data.update({key: value for key, value in user_data.items() if key not in cls.OA_NOT_UPDATE_FIELDS})
            else:
                user.user_data.update({k: v for k, v in user_data.items() if v not in [None, '']})
            flag_modified(user, 'user_data')
        if options.get('role_id'):
            role = db_session.query(Role).filter(Role.id == int(options['role_id'])).first()
            if role:
                user.roles = [role]
                user.permissions = [cls.P_MANAGE] if role.super_admin else []
                if config.get_config('sys') == 'cmbchina':
                    if business_system_code := role.role_data.get('business_system_code'):
                        user.user_data['business_system_code'] = business_system_code
                    if business_system_name := role.role_data.get('business_system_name'):
                        user.user_data['business_system_name'] = business_system_name
                    flag_modified(user, 'user_data')
        user.is_oa = is_oa
        if update_flag:
            user.department_id = department_ins.id if department_ins else None
        if password:
            user.set_password(password)
        db_session.add(user)
        if options.get('clear_password'):
            user.password = None
        db_session.commit()
        return user

    @classmethod
    def create_ht_user_from_auth_api(cls, uid, ext_uname, username=None):
        default_department_id = '999999'
        default_department = '其他部门'
        head_quarter = (
            db_session.query(Department)
            .filter(Department.parent_id == '-1', Department.department_type == Department.HT_PRIMARY_SECTOR, Department.deleted == 0)
            .first()
        )
        parent_id = head_quarter.external_id if head_quarter else None
        department_ins = Department.init(default_department_id, default_department, parent_id=parent_id, department_type=Department.HT_OTHER_DEPARTMENT)
        department_ins_id = department_ins.id if department_ins else None
        user_data = User.make_user_data(
            uid=uid, ext_uname=ext_uname, department=default_department, department_id=default_department_id, username=username, allow_login=False
        )
        user = User(ext_uname=ext_uname, user_data=user_data, is_oa=True, department_id=department_ins_id, deleted=User.HT_USER_STATUS_ABNORMAL)
        db_session.add(user)
        db_session.commit()
        return user

    @classmethod
    def transfer_work_status(cls, work_status_string):
        if not work_status_string:
            return None
        if work_status_string not in cls.KYSEC_USER_STATUS_MAP.values():
            return None
        reverse_map = {v: k for k, v in cls.KYSEC_USER_STATUS_MAP}
        return reverse_map[work_status_string]

    @classmethod
    def get_by_id(cls, user_id):
        user = db_session.query(User).filter(User.id == int(user_id), User.deleted == 0).first()
        if not user:
            return None
        return user

    @classmethod
    def get_by_ext_uname(cls, ext_uname):
        user = db_session.query(cls).filter(cls.ext_uname == ext_uname, cls.deleted == 0).first()
        if not user:
            return None
        return user

    @classmethod
    def create_tmp_ins(cls, data):
        new_ist = cls()
        for key, val in data.items():
            if key == "roles":
                new_ist.roles = [Role.create_tmp_ins(item) for item in val]
            else:
                setattr(new_ist, key, val)
        return new_ist

    def to_dict(self):
        role_data = [role.to_dict() for role in self.roles]
        if config.get_config('sys') == "cmbchina" and self.is_super_admin:
            for item in role_data:
                for app in ['glazer', 'glazer_imitator']:
                    item['permission'][app] = [_item for _item in item['permission'].get(app) or [] if _item not in ['admin', 'imitator_admin']]
        permissions = self.permissions
        user_data = {}
        config_sys = config.get_config('sys')
        copy_user_data_flag = config_sys in ['kysec', 'zts', 'cjsc', 'ht']
        if copy_user_data_flag:
            user_data = deepcopy(self.user_data)
            if config_sys == 'kysec':
                work_status = user_data.get('work_status')
                if work_status is not None and work_status in User.KYSEC_USER_STATUS_MAP:
                    user_data['work_status'] = User.KYSEC_USER_STATUS_MAP[work_status]
            elif config_sys == 'zts':
                departments = Department.find_departments_by_external_id(user_data.get('department_id'))
                departments = [item for item in departments if item.name != '中泰证券股份有限公司']
                if departments:
                    user_data['department'] = departments[0].name
                user_data['display_department'] = '/'.join(department.name for department in departments[::-1]) if departments else None
            elif config_sys == 'cjsc':
                departments = Department.find_departments_by_external_id(user_data.get('department_id'))
                user_data['display_department'] = '-'.join(department.name for department in departments[::-1])
            elif config_sys == 'ht':
                user_data.pop('autodoc_data', None)
                user_data.pop('categories', None)

        data = {
            'id': self.id,
            'user_data': user_data if copy_user_data_flag else self.user_data,
            'ext_uname': self.ext_uname,
            'permissions': permissions,
            'resign': self.resign,
            'deleted': self.deleted,
            'created_utc': self.created_utc,
            'updated_utc': self.updated_utc,
            'roles': role_data,
            'oa_user': self.oa_user,
            'is_super_admin': self.is_super_admin,
            'is_oa': self.is_oa,
            'is_admin': self.is_admin,
            'department_id': self.department_id,
            'allow_login': self.allow_login,
            'process_time': self.process_time,
            'has_password': bool(self.password),
        }
        if config == 'cjsc':
            data.update(
                {
                    'business_segment': self.business_segment,
                    'business_departments': self.business_departments,
                    'business_project_types': self.business_project_types,
                }
            )
        return data

    def __repr__(self):
        return "<User: {} {}>".format(self.id, self.ext_uname)


class VisitSys(Enum):
    TRIDENT = 'trident'
    USER_MANAGE = 'user_manage'
    FAULTY_WORDING = 'faulty_wording'


class VisitRecord(BaseModel):
    __tablename__ = 'visit_records'

    id = Column(Integer, primary_key=True)
    visit_sys = Column(String, nullable=False)
    api = Column(String)
    ip_address = Column(String)
    user_id = Column(Integer, ForeignKey("user.id"))
    deleted = Column(Integer, default=0)
    record_data = Column(JSONB)
    created_utc = Column(Integer, default=generate_timestamp)
    updated_utc = Column(Integer, default=generate_timestamp, onupdate=generate_timestamp)

    user = relationship("User", back_populates="visit_records", uselist=False, lazy="select")

    @classmethod
    def create(cls, user_id, visit_sys, api=None, ip_address=None, record_data=None):
        visit_record = VisitRecord()
        visit_record.user_id = user_id
        visit_record.api = api
        visit_record.ip_address = ip_address
        visit_record.visit_sys = visit_sys
        visit_record.record_data = record_data
        db_session.add(visit_record)
        db_session.commit()
        return visit_record

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'visit_sys': self.visit_sys,
            'deleted': self.deleted,
            'api': self.api,
            'ip_address': self.ip_address,
            'username': self.user.user_data.get('username') or self.user.ext_uname if self.user else '',
            # 'user': self.user.to_dict() if self.user else None,
            'created_utc': self.created_utc,
            'updated_utc': self.updated_utc,
            'record_data': self.record_data,
        }


class SysRequire(BaseModel):
    __tablename__ = 'sys_require'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"))
    sys = Column(String, nullable=False)
    status = Column(Integer, default=RequireStatus.default.value)
    project_name = Column(String)
    reason = Column(
        String,
    )
    created_utc = Column(Integer, default=generate_timestamp)
    updated_utc = Column(Integer, default=generate_timestamp, onupdate=generate_timestamp)
    start_utc = Column(Integer, nullable=False)
    end_utc = Column(Integer, nullable=False)

    user = relationship("User", back_populates="required_sys", lazy="subquery")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "sys": self.sys,
            "project_name": self.project_name,
            "reason": self.reason,
            "status": self.status,
            "created_utc": self.created_utc,
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
        }


class Department(BaseModel):
    __tablename__ = 'departments'

    HT_PRIMARY_SECTOR = 0  # 海通一级部门及总部
    HT_SECONDARY_SECTOR = 1  # 二级部门
    HT_BRANCH = 2  # 分公司
    HT_BUSINESS_DEPARTMENT = 3  # 营业部
    HT_OTHER_DEPARTMENT = 4  # 其他部门

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    allow_login = Column(Boolean, nullable=False, default=True)
    parent_id = Column(String)
    external_id = Column(String, unique=True)
    department_type = Column(Integer)
    deleted = Column(Integer, default=0)
    data = Column(JSONB)
    created_utc = Column(Integer, default=generate_timestamp)
    updated_utc = Column(Integer, default=generate_timestamp, onupdate=generate_timestamp)

    users = relationship("User", back_populates="department", lazy="joined")

    @classmethod
    def find_departments_by_external_id(cls, external_id: str, find_parent=True):
        """
        WITH RECURSIVE cte AS (
            SELECT *
            FROM departments
            WHERE external_id = %(external_id)s
            UNION ALL
            SELECT d.*
            FROM departments d
                 INNER JOIN cte ON d.external_id = cte.parent_id # 查找父
                 # INNER JOIN cte ON d.parent_id = cte.external_id # 查找子
        )
        SELECT * FROM cte;
        """
        cte_query = db_session.query(Department).filter(Department.external_id == external_id).cte(recursive=True, name="result")
        main_alias = aliased(Department, name="L")
        cte_alias = aliased(cte_query, name="R")
        cond = main_alias.external_id == cte_alias.c.parent_id if find_parent else main_alias.parent_id == cte_alias.c.external_id
        query = cte_query.union_all(db_session.query(main_alias).join(cte_alias, cond))
        return db_session.query(query).all()

    @classmethod
    def init(cls, external_id, name, parent_id=None, department_type=None, data=None):
        if not external_id:
            return None
        instance = db_session.query(cls).filter(cls.external_id == external_id).first()
        if not instance:
            instance = cls(external_id=external_id, name=name, parent_id=parent_id, department_type=department_type, data=data)
            db_session.add(instance)
            try:
                db_session.commit()
            except IntegrityError:
                db_session.rollback()
        if instance.deleted:
            instance.deleted = 0
        instance.name = name
        if parent_id:
            instance.parent_id = parent_id
        if department_type is not None:
            instance.department_type = department_type
        if data:
            org_department_data = instance.data or {}
            org_department_data.update(data)
            instance.data = org_department_data
            flag_modified(instance, 'data')
        return instance

    @classmethod
    def make_secondary_department(cls, department, parent_id, department_type, department_data=None):
        instance = db_session.query(cls).filter(cls.name == department, cls.parent_id == parent_id).first()
        if not instance:
            instance = cls(name=department, parent_id=parent_id, department_type=department_type, data=department_data)
            db_session.add(instance)
            db_session.flush()
            instance.external_id = f'secondary_{instance.id}'
            db_session.commit()
            return instance

        if instance.deleted:
            instance.deleted = 0
        if department_data:
            instance.data = department_data
            flag_modified(instance, 'data')
        db_session.commit()
        return instance

    def to_dict(self, detail=False):
        ret = {
            "id": self.id,
            "name": self.name,
            "allow_login": self.allow_login,
            'children': [],
            "parent_id": self.parent_id,
            "external_id": self.external_id,
            'department_type': self.department_type,
            "deleted": self.deleted,
            'data': self.data,
            'created_utc': self.created_utc,
            'updated_utc': self.updated_utc,
            'department_id': self.external_id,  # TODO remove ht field
            'department': self.name,
            'department_data': self.data,
        }
        if detail:
            if config.get_config('sys') == 'ht':
                ret['users'] = [user.to_dict() for user in self.users if user.deleted == User.USER_STATUS_DEFAULT or user.allow_login]
            else:
                ret['users'] = [user.to_dict() for user in self.users if user.deleted == User.USER_STATUS_DEFAULT]
        return ret


class LDAPUserRecord(BaseModel):
    __tablename__ = 'ldap_user_record'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"))
    department_id = Column(String)
    department = Column(String)
    created_utc = Column(Integer, default=generate_timestamp)
    updated_utc = Column(Integer, default=generate_timestamp, onupdate=generate_timestamp)

    user = relationship('User', back_populates='ldap_user_record')


class CustomerSysConfig(BaseModel):
    __tablename__ = 'customer_sys_config'

    id = Column(Integer, primary_key=True)
    sync_user = Column(Boolean)
    disable_former_employee = Column(Boolean)
    meta = Column(JSONB)

    def to_dict(self):
        return {'id': self.id, 'sync_user': self.sync_user, 'disable_former_employee': self.disable_former_employee, 'meta': self.meta}
