# pylint: disable=too-many-locals
import json
import logging

import requests
from sqlalchemy import true, distinct, or_
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql.functions import count

from user_proxy import config
from user_proxy.common.rpc_web_service.common import check_user
from user_proxy.common.rpc_web_service.web_service_base import WebServiceBase, get_off_redirect_url, get_user_sys_permission
from user_proxy.db import db_session
from user_proxy.handlers.message import USER_NOT_EXISTS, PERMISSION_DENIED
from user_proxy.models.user import User, SysRequire, RequireStatus, VisitRecord, LDAPUserRecord
from user_proxy.utils.authtoken import generate_timestamp
from user_proxy.utils.cas import create_url
from user_proxy.utils.sm4_util import SM4Util


class ProxyWebService(WebServiceBase):
    @classmethod
    @check_user
    def get_off(cls, current_user, origin_host, arguments, user_id, **kwargs):
        if not user_id:
            user = current_user
        else:
            user = User.get_by_id(user_id)
        system = arguments.get('sys', 'autodoc_overall')
        if not cls.valid_system_permission(system, user):
            return cls.error('此用户无权限访问', html=True)
        if not get_user_sys_permission(user, system):
            return cls.error('您不具备该子系统访问权限')

        url = get_off_redirect_url(system, user, current_user, origin_host, **arguments)
        if not url:
            return cls.error('sys: {} not config'.format(system))
        return cls.redirect(url)

    @classmethod
    def get_visit_stat(cls, start_utc, end_utc, **kwargs):
        cond = true()
        user_cond = true()
        if start_utc is not None:
            cond &= VisitRecord.updated_utc >= start_utc
            user_cond &= User.created_utc >= start_utc
        if end_utc is not None:
            cond &= VisitRecord.updated_utc < end_utc
            user_cond &= User.created_utc < end_utc
        people_count = db_session.query(count(User.id)).filter(user_cond).scalar()
        visit_record_query = (
            db_session.query(VisitRecord.visit_sys, count(VisitRecord.id), count(distinct(VisitRecord.user_id))).filter(cond).group_by(VisitRecord.visit_sys)
        )
        stat_res = {'total': people_count, **{item[0]: {'visit_count': item[1], 'people_count': item[2]} for item in visit_record_query}}
        for need_sys in ['pdflux', 'calliper', 'faulty_wording']:
            stat_res.setdefault(need_sys, {'visit_count': 0, 'people_count': 0})
        return cls.data(stat_res)

    @classmethod
    @check_user
    def me(cls, current_user, **kwargs):  # pylint: disable=invalid-name
        ret_data = current_user.to_dict()

        if config.get_config('unify_auth.enable_sys_require', False):
            now_stamp = generate_timestamp()
            if current_user.permissions and User.P_MANAGE in current_user.permissions:
                ret_data["need_verify_count"] = (
                    db_session.query(count(SysRequire.id)).filter(SysRequire.end_utc > now_stamp, SysRequire.status == RequireStatus.default.value).scalar()
                )
            else:
                exists_requires = current_user.required_sys.filter(SysRequire.end_utc > now_stamp).all()
                ret_data['sys_requires'] = [require.to_dict() for require in exists_requires]
                for require in exists_requires:
                    if require.status == RequireStatus.approved.value:
                        if ret_data["roles"]:
                            permission = ret_data["roles"][0]["permission"]
                            permission.setdefault(require.sys, []).append("normal")
                        else:
                            ret_data["roles"] = [
                                {
                                    "id": 0,
                                    "name": "approved_require",
                                    "permission": {require.sys: ["normal"]},
                                    "created_utc": now_stamp,
                                    "updated_utc": now_stamp,
                                    "oa_default": False,
                                    "user_count": 1,
                                }
                            ]
        return cls.data(ret_data)

    @classmethod
    def login_precheck(cls, uid):
        user = db_session.query(User).filter(User.ext_uname == uid, not User.permissions.any(User.P_MANAGE), User.resign.is_(False), User.deleted == 0).first()
        if not user:
            return cls.error(USER_NOT_EXISTS)
        return cls.data()

    @classmethod
    def ldap_login(cls, uid, ext_uname, department, department_id, username, user_dn, **kwargs):  # pylint:disable=too-many-positional-arguments
        custom_sys = config.get_config('sys')
        if custom_sys == 'ht':
            # 用户调整，根据uid重新定位到user, ext_uname数据不更新，仍用旧的ldap user_dn数据，保证子系统项目对应
            #    uid     ext_uname
            # 旧 013266  uid=013266,o=0145,o=znbm,o=GS001
            # 新 013266  uid=013266,o=0112,o=znbm,o=GS001
            user = (
                db_session.query(User)
                .filter(or_(User.ext_uname == user_dn, User.ext_uname == uid, User.user_data.op('->>')('uid') == uid), User.is_oa.is_(True))
                .first()
            )
            # 1. 如果Ldap认证通过，且数据仓库同步过来的用户表里面也有这个用户，
            #    则正常登录，也不更新其部门名称和部门号。
            if user:
                if user.ext_uname == uid:
                    user.ext_uname = user_dn
                    user.user_data['ext_uname'] = user_dn
                    flag_modified(user, 'user_data')
            else:
                # 2. 如果Ldap认证通过，但数据仓库同步过来的用户表里面没有这个用户，
                # 那就给其设置一个缺省的部门名称和部门号（其它部门、999999，上级部门就是总部），
                # 同时另一个表中记录下他的Ldap认证时的部门名称和部门号（参考foundry）
                # 默认不能登陆,需等管理员修改该用户的allow_login
                user = User.create_ht_user_from_auth_api(uid, user_dn, username)
                ldap_user_record = LDAPUserRecord(user_id=user.id, department_id=department_id, department=department)
                db_session.add(ldap_user_record)
            db_session.commit()
            if user.deleted == User.USER_STATUS_DELETED:
                return cls.error('该用户已被删除')
            if not user.allow_login:
                return cls.error('该用户已被禁止登录')
        elif custom_sys == 'kysec':
            # for kysec using uid
            # ldap只做认证，不更新username及部门信息
            user = User.make_user(uid=uid, ext_uname=ext_uname)
        else:
            user = User.make_user(uid=uid, ext_uname=ext_uname, department=department, department_id=department_id, username=username)
        if not user:
            return cls.error('permission denied')
        work_status = user.user_data.get('work_status', '')
        if custom_sys == 'kysec' and work_status != User.STATUS_OFFICILA:
            return cls.error(PERMISSION_DENIED)
        return cls.data(user.to_dict())

    @staticmethod
    def get_decrypt_data(auth_url):
        json_data = {}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        logging.info('get encrypt token url: %s', auth_url)
        try:
            resp = requests.get(auth_url, headers=headers, timeout=int(config.get_config('csits_auth.timeout', 30)), verify=False)
            if resp.status_code != 200:
                logging.error('get token failed: %s', resp.status_code)
                logging.info('resp: %s', resp.text)
            res = resp.json()
            logging.debug('resp json data: %s', res)
            encrypt_token = res['data']
            logging.info('encrypt_token: %s', encrypt_token)

            secret_key = config.get_config('csits_auth.secret_key')
            sm4_ins = SM4Util()
            decrypt_data = sm4_ins.decrypt_sm4(secret_key, encrypt_token, mode='ECB')
            logging.info('decrypt_data: %s', decrypt_data)
            json_data = json.loads(decrypt_data)
        except Exception as e:
            logging.exception(e)
        return json_data

    @staticmethod
    def get_csits_url(api, *params):
        auth_host = config.get_config('csits_auth.department_host')
        sys_code = config.get_config('csits_auth.sys_code')
        url = create_url(auth_host, api, ("sysCode", sys_code), *params)
        return url

    @staticmethod
    def get_department_info(json_data):
        department = department_id = username = None
        try:
            dept_data = json_data['orgUnitResults'][0]
            department = dept_data['deptName']
            department_id = dept_data['deptId']
            username = json_data['userName']
        except Exception as e:
            logging.exception(e)
        return department, department_id, username

    @classmethod
    def get_user_info(cls, uid):
        department_data = cls.get_decrypt_data(cls.get_csits_url(config.get_config('csits_auth.department_api'), ("userId", uid)))
        department, department_id, username = cls.get_department_info(department_data)
        user_role_data = cls.get_decrypt_data(cls.get_csits_url(config.get_config('csits_auth.user_role_api'), ("userId", uid)))
        user_role = ','.join([item['roleName'] for item in user_role_data if item['roleCode'].startswith('srbs-gateway-front')])
        main_dept_data = cls.get_decrypt_data(cls.get_csits_url(config.get_config('csits_auth.main_department_api'), ("userId", uid)))
        org_dept_id = main_dept_data[0]['orgCode']
        full_dept_name = f"{main_dept_data[0]['parentName']}-{main_dept_data[0]['orgName']}"
        return department, department_id, username, user_role, org_dept_id, full_dept_name

    @classmethod
    def get_uid_by_acc(cls, account_number):
        user_info = cls.get_decrypt_data(cls.get_csits_url(config.get_config('csits_auth.user_info_api'), ("acctNbr", account_number)))
        return user_info.get("userId", "")

    @classmethod
    def get_user_info_by_acc(cls, account_number):
        user_info = cls.get_decrypt_data(
            cls.get_csits_url(config.get_config('csits_auth.user_info_api'), ("acctNbr", account_number)))
        return user_info or {}

    @classmethod
    def get_org_unit_tree(cls):
        user_tree = cls.get_decrypt_data(
            cls.get_csits_url(config.get_config('csits_auth.org_unit_tree_api'))
        )
        return user_tree or []

    @classmethod
    def get_org_user_infos(cls, org_id):
        user_tree = cls.get_decrypt_data(
            cls.get_csits_url(config.get_config('csits_auth.org_user_infos_api'), ("orgId", org_id))
        )
        return user_tree or []

    @classmethod
    def get_user_infos(cls, username):
        user_tree = cls.get_decrypt_data(
            cls.get_csits_url(config.get_config('csits_auth.user_infos_api'), ("userName", username))
        )
        return user_tree or []

    @classmethod
    def cas_login(cls, cas_res, **kwargs):
        logging.error('ticket auth success: cas_res=%s', cas_res)
        cas_prefix = config.get_config('cas_auth.cas_prefix', 'cas:')
        uid = cas_res[f'{cas_prefix}user']
        config_sys = config.get_config('sys')
        if config_sys == 'csc':
            ext_uname = cas_res['cas:attributes']['cas:employeeNo']
        else:
            ext_uname = uid
        if config_sys == 'cjsc':
            user = db_session.query(User).filter(User.ext_uname == ext_uname, User.deleted == 0).first()
        elif config_sys == 'essence':
            # uid: zhangsan, ext_uname: 1650e41476203da705685d4477eaee2a(唯一)
            ext_uname = cas_res['cas:attributes']['cas:userId']
            username = cas_res['cas:attributes']['cas:realname']
            phone = cas_res['cas:attributes']['cas:phone']
            email = cas_res['cas:attributes']['cas:email']
            user = User.make_user(uid=uid, ext_uname=ext_uname, username=username, email=email, phone=phone, _from='cas')
        elif config_sys == 'csits' and config.get_config('csits_auth.department_enable', False):
            csits_id = cas_res['cas:attributes']['cas:id']
            department, department_id, username, user_role, org_dept_id, full_dept_name = cls.get_user_info(csits_id)
            user = User.make_user(
                uid=csits_id,
                ext_uname=ext_uname,
                department=department,
                department_id=department_id,
                username=username,
                user_role=user_role,
                _from='cas',
                org_dept_id=org_dept_id,
                full_dept_name=full_dept_name,
            )
        elif config_sys == 'cmfchina':
            user = User.make_user(
                uid=uid,
                ext_uname=ext_uname,
                username=cas_res['cas:attributes'].get('cas:name_zh'),
                email=cas_res['cas:attributes'].get('cas:email'),
                _from='cas',
                clear_password=True,
            )
            if not user:
                return cls.error('permission denied')
            if not user.user_data.get('business_system_code'):
                return cls.redirect('/#/wrongPermissions')
        elif config_sys == 'mszq':
            ext_uname = cas_res['attributes']['cas:user_id']
            user = User.make_user(uid=ext_uname, ext_uname=ext_uname, username=cas_res['attributes']['cas:full_name'], _from='cas', custom_system='cas')
        else:
            user = User.make_user(uid=uid, ext_uname=ext_uname, username=ext_uname, _from='cas')
        if not user:
            if config_sys == 'cjsc':
                return cls.redirect('/#/notValidUser')
            else:
                return cls.error('permission denied')
        return cls.data(user.to_dict())
