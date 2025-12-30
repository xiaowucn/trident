# pylint:skip-file
import datetime
import json
import logging
import os
from collections import defaultdict

import requests
from invoke import task
from prettytable import PrettyTable
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.attributes import flag_modified
from utensils.util import generate_timestamp

from user_proxy import config
from user_proxy.common.rpc_web_service.web_service_base import get_off_redirect_url
from user_proxy.db import db_session
from user_proxy.worker.ht import get_and_load_data_file_func, load_data_file_func
from user_proxy.models.user import User, Role, Department


class CustomPrettyTable(PrettyTable):
    def _format_value(self, field, value):
        if isinstance(value, int) and field in self._int_format:
            value = ("%%%sd" % self._int_format[field]) % value
        elif isinstance(value, float) and field in self._float_format:
            value = ("%%%sf" % self._float_format[field]) % value
        elif isinstance(value, dict):
            value = json.dumps(value)
        return str(value)


@task
def serve(ctx):
    from user_proxy.server import serve as _serve

    _serve()


def format_print_users(users):
    if not users:
        print("no users found")
        return
    if not isinstance(users, list):
        users = [users]
    table = CustomPrettyTable(['user_id', 'username', 'permissions', 'user_data', 'role_ids', 'deleted'])
    for user in users:
        table.add_row([user.id, user.ext_uname, user.permissions, user.user_data, [role.id for role in user.roles], user.deleted])
    print(table)


def format_print_roles(roles):
    if not roles:
        print("no roles found")
        return
    if not isinstance(roles, list):
        roles = [roles]
    table = CustomPrettyTable(['role_id', 'name', 'permission', 'oa_default'])
    for role in roles:
        table.add_row([role.id, role.name, role.permission, role.oa_default])
    print(table)


@task
def list_users(ctx):
    users = db_session.query(User).order_by(User.id.desc()).all()
    format_print_users(users)


@task
def list_roles(ctx):
    roles = db_session.query(Role).order_by(Role.id.desc()).all()
    format_print_roles(roles)


@task(
    help={
        'role-ids': "使用,分隔的字符串，比如1,2,3",
        'permissions': "用户权限，admin为管理员，其他则为普通用户，不传则不修改",
    }
)
def modify_user(ctx, user_id, ext_uname=None, password=None, role_ids=None, permissions=None, username=None):
    user = db_session.query(User).filter(User.id == user_id).first()
    if not user:
        print(f"user: {user_id} not found")
    if ext_uname is not None:
        user.ext_uname = ext_uname
        user.user_data['uid'] = ext_uname
        user.user_data['ext_uname'] = ext_uname
        user.user_data['username'] = username if username else ext_uname
    if password is not None:
        user.set_password(password)
    if role_ids is not None:
        role_ids = role_ids.split(",")
        roles = db_session.query(Role).filter(Role.id.in_(role_ids)).all()
        if not roles:
            print(f"role: {role_ids} not found")
        else:
            # print('roles found:\n')
            # format_print_roles(roles)
            user.roles = roles
    if permissions is not None:
        if permissions == 'admin':
            user.permissions = [User.P_MANAGE]
        else:
            user.permissions = []
    # user.user_data['ext_sys'] = config.get_config('sys')
    # user.user_data['_from'] = config.get_config('sys')
    flag_modified(user, 'user_data')
    db_session.add(user)
    db_session.commit()
    print('{} modified successfully: \n'.format(user))
    format_print_users(user)


@task
def add_role(ctx, name, permission, oa_default):
    role = Role()
    permission = json.loads(permission)
    role.name = name
    role.permission = permission
    if oa_default == 'true':
        oa_default_role = db_session.query(Role).filter(Role.oa_default.is_(True)).first()
        if oa_default_role:
            oa_default_role.oa_default = False
        role.oa_default = True
    else:
        role.oa_default = False
    db_session.add(role)
    db_session.commit()
    print('{} added successfully: \n'.format(role))
    format_print_roles(role)


@task
def modify_role(ctx, role_id, name=None, permission=None, oa_default=None):
    role = db_session.query(Role).filter(Role.id == role_id).first()
    if not role:
        print("role: %s not found" % role_id)
    if permission is not None:
        permission = json.loads(permission)
        role.permission = permission
        flag_modified(role, '_permission')
    if name is not None:
        role.name = name
    if oa_default is not None:
        if oa_default == 'true':
            oa_default_role = db_session.query(Role).filter(Role.oa_default.is_(True)).first()
            if oa_default_role:
                oa_default_role.oa_default = False
            role.oa_default = True
        else:
            role.oa_default = False
    db_session.add(role)
    db_session.commit()
    print('{} modified successfully: \n'.format(role))
    format_print_roles(role)


@task
def add_manager(ctx, user_dn, password, username=None, secondary_admin=None):
    user = db_session.query(User).filter(User.ext_uname == user_dn, User.deleted == 0).first()
    if not user:
        user = User(ext_uname=user_dn)
    user.set_password(password)
    user.permissions = [User.P_MANAGE]
    role = db_session.query(Role).filter(Role.name == Role.manager).first()
    if not role:
        print('can not find default role')
        return
    user_data = {'uid': user_dn, 'ext_uname': user_dn, 'ext_sys': 'self', 'username': username if username else user_dn, '_from': 'self'}
    # 世纪证券二级管理员标记，前端做权限及界面限制用
    if secondary_admin:
        user_data['secondary_admin'] = True
    user.roles = [role]
    user.user_data = user_data
    user.is_admin = True
    user.is_oa = False
    flag_modified(user, 'user_data')
    db_session.add(user)
    db_session.commit()
    print('{} added successfully: \n'.format(user))
    format_print_users(user)


@task
def delete_role(ctx, name):
    db_session.query(Role).filter(Role.name == name).delete()
    db_session.commit()


@task(
    help={
        'user_dn': "用户ext_uname字段",
        'role_id': "角色id（int），根据需要设定对应角色id，可以用inv web.list-roles查看数据库所有角色信息",
    }
)
def add_user(ctx, user_dn, password, role_id: int, department_id=None, username=None):
    user = db_session.query(User).filter(User.ext_uname == user_dn, User.deleted == 0).first()
    if user:
        print('user {} already exists'.format(user_dn))
        return
    user = User(ext_uname=user_dn)
    user.set_password(password)
    user.permissions = []
    role = db_session.query(Role).filter(Role.id == int(role_id)).first()
    if not role:
        print('role {} not found'.format(role_id))
        return
    user_data = {
        'uid': user_dn,
        'ext_uname': user_dn,
        'ext_sys': config.get_config('sys'),
        'username': username if username else user_dn,
        'department_id': department_id,
        '_from': 'self',
    }
    user.roles = [role]
    user.user_data = user_data
    user.is_oa = False
    db_session.add(user)
    db_session.commit()
    print('{} added successfully: \n'.format(user))
    format_print_users(user)


@task
def add_test_user_for_zts(ctx, ext_uname, username, password, department):
    user = db_session.query(User).filter(User.ext_uname == ext_uname, User.deleted == 0).first()
    if user:
        print('user {} already exists'.format(ext_uname))
        return
    user = User(ext_uname=ext_uname)
    user.set_password(password)
    user.permissions = []
    department_ins = db_session.query(Department).filter(Department.name == department).first()
    department_ins: Department
    user_data = {
        'uid': ext_uname,
        'ext_uname': ext_uname,
        'ext_sys': config.get_config('sys'),
        'username': username,
        'department': department,
        'department_id': department_ins.external_id if department_ins else None,
        '_from': 'self',
        'no_permission': True,
    }
    user.roles = []
    user.user_data = user_data
    user.is_oa = False
    db_session.add(user)
    db_session.commit()
    print('{} added successfully: \n'.format(user))
    format_print_users(user)


@task
def modify_user_password(ctx, user_dn, password):
    user = db_session.query(User).filter(User.ext_uname == user_dn).first()
    if not user or not password:
        logging.warning('user_dn or password not valid')
        return
    user.set_password(password)
    db_session.add(user)
    db_session.commit()
    logging.warning('user password modified!')


@task
def delete_oa_user(ctx):
    count = db_session.query(User).filter(User.is_oa.is_(True)).delete()
    db_session.commit()
    logging.warning("删除oa用户条目数：{}".format(count))


@task
def delete_department(ctx):
    count = db_session.query(Department).delete()
    db_session.commit()
    logging.warning("删除部门条目数：{}".format(count))


@task
def fix_ht_ldap_users(ctx):
    db_users = db_session.query(User).filter(User.is_oa.is_(True)).all()
    uid_users_map = defaultdict(list)
    for db_user in db_users:
        if (db_user.user_data or {}).get('uid'):
            uid_users_map[db_user.user_data['uid']].append(db_user)

    for uid, users in uid_users_map.items():
        if len(users) <= 1:
            continue
        sorted_users = sorted(users, key=lambda x: x.id)
        for user in sorted_users[1:]:
            db_session.delete(user)
            logging.warning(
                "删除用户：uid=%s, id=%s, ext_uname=%s, 保留用户：id=%s, ext_uname=%s",
                uid,
                user.id,
                user.ext_uname,
                sorted_users[0].id,
                sorted_users[0].ext_uname,
            )
    db_session.commit()


@task
def get_and_load_data_file(ctx, domain=None, account=None, password=None, user_path=None, depart_path=None, debug=False):
    get_and_load_data_file_func(domain, account, password, user_path, depart_path, debug)


@task
def load_data_file(ctx, user_file, dept_file, debug=False):
    # with db_session.begin():
    load_data_file_func(user_file, dept_file, debug)


@task
def modify_user_password_expired_time(ctx, user_id, deadline=None, increase_time=7776000):
    user = db_session.query(User).filter(User.id == int(user_id), User.deleted == 0).first()
    if not user:
        print('user {} is not existed'.format(user_id))
        return
    password_expired_time = generate_timestamp() + int(increase_time) if deadline is None else int(deadline)
    user.user_data['password_expired_time'] = password_expired_time
    flag_modified(user, 'user_data')
    db_session.commit()
    print('{} modify expired_time successfully: \n'.format(user))
    format_print_users(user)


@task
def add_oa_user(ctx, ext_uname, role_id):
    roles = db_session.query(Role).filter(Role.id.in_([int(role_id)])).all()
    print(roles)
    user = User.make_oa_user(ext_uname, roles)
    print('add oa user successfully: \n {}'.format(user))


@task
def trigger_subsystem(ctx, system, host=''):
    print("start trigger subsystem")
    users = db_session.query(User).all()
    for user in users:
        url = get_off_redirect_url(system, user, origin_host=host)
        res = requests.get(url)
        print(res.status_code, url)


@task
def update_swhysc_autodoc_user_info(ctx, dsn_url):
    """更新申万宏源部门数据"""
    customer_engine = create_engine(dsn_url)
    CustomerDBSession = sessionmaker(customer_engine)  # pylint: disable=invalid-name
    autodoc_db_session = CustomerDBSession()
    user_map = dict(db_session.query(User.ext_uname, User))
    autodoc_users = autodoc_db_session.execute('select ext_uname from "user"').fetchall()

    for autodoc_user in autodoc_users:
        if user_ins := user_map.get(autodoc_user[0]):
            department_id = user_ins.user_data.get('department_id') or ''
            autodoc_db_session.execute(
                'update "user" set ext_group_id = :department_id where ext_uname = :ext_uname',
                {'department_id': department_id, 'ext_uname': user_ins.ext_uname},
            )
            print(f"update ext_uname: {user_ins.ext_uname}, department_id: {department_id}")
    autodoc_db_session.commit()
    print('all user info updated!')


@task
def add_rsm(ctx, uname, uid, role_id=1):
    user = db_session.query(User).filter(User.ext_uname == uname, User.deleted == 0).first()
    if user:
        print('user {} already exists'.format(uname))
        return
    user = User(ext_uname=uname)
    user.set_password('rsm123')
    user.permissions = []
    role = db_session.query(Role).filter(Role.id == role_id).first()
    if not role:
        print('role {} not found'.format(role_id))
        return
    user_data = {
        'uid': uid,
        'ext_uname': uname,
        'ext_sys': config.get_config('sys'),
        'username': uname,
        'department_id': None,
        '_from': 'self',
    }
    user.roles = [role]
    user.is_oa = False
    user.user_data = user_data
    db_session.add(user)
    db_session.commit()
    print('{} added successfully: \n'.format(user))
    format_print_users(user)


@task
def gen_jwk(ctx, kid: str, alg="RSA-OAEP", use="enc") -> None:
    """
    Generate JSON Web Key

    Args:
        kid: Key ID
        alg: Algorithm (RS256, PS256, ES256, HS256, RSA-OAEP, ECDH-ES, A256KW, etc.)
        use: Key usage ('sig' for signature, 'enc' for encryption)
    """
    from user_proxy.config import project_root
    from jwcrypto import jwk

    if alg in ("RS256", "PS256") or alg == "RSA-OAEP":
        key = jwk.JWK.generate(kty='RSA', size=2048, alg=alg, use=use, kid=kid)
        private_jwk = json.loads(key.export_private())
        public_jwk = json.loads(key.export_public())

    elif alg == "ES256" or alg == "ECDH-ES":
        key = jwk.JWK.generate(kty='EC', crv='P-256', alg=alg, use=use, kid=kid)
        private_jwk = json.loads(key.export_private())
        public_jwk = json.loads(key.export_public())

    elif alg == "HS256" or alg.startswith("A"):
        key = jwk.JWK.generate(kty='oct', size=256, alg=alg, use=use, kid=kid)
        key_json = key.export(as_dict=True)
        private_jwk = public_jwk = key_json
    else:
        raise ValueError(f"unsupported alg: {alg}")

    timestamp = datetime.datetime.now().isoformat() + "Z"

    for suffix, jwk_dict in (("private_key.json", private_jwk), ("public_key.json", public_jwk)):
        jwk_dict.update(created=timestamp)
        path = os.path.join(project_root, "data", "keys", f"{kid}_jwe_{suffix}")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(jwk_dict, f)
        print(path)
