import logging
from typing import Dict, List
from urllib.parse import unquote

import requests
from sqlalchemy.orm import aliased
from utensils.util import generate_timestamp

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.handlers.base import BaseHandler, permission_auth, route
from user_proxy.models.user import Department, User
from user_proxy.utils.cas import create_url, decrypt_ctsec_token

USER_REQUEST_SERVER = config.get_config('ctsec.user.server')
USER_REQUEST_URI = config.get_config('ctsec.user.uri')


class Cache:
    __cache__: Dict[int, dict] = None
    last_updated_at = None

    @classmethod
    def load(cls):
        expired = cls.last_updated_at is None or generate_timestamp() - cls.last_updated_at > 24 * 60 * 60
        if cls.__cache__ is None or expired:
            cls.__cache__ = cls.fetch()
            cls.last_updated_at = generate_timestamp()

    @classmethod
    def fetch(cls) -> dict:
        raise NotImplementedError


class ExternalDepartment:
    @classmethod
    def find_by_id(cls, dept_id: int) -> bool:
        department = db_session.query(Department).filter(Department.external_id == str(dept_id)).first()
        return department is not None and department.allow_login

    @classmethod
    def find_offsprings(cls, model_ids: List[int]):
        """
        WITH RECURSIVE cte AS (
            SELECT *
            FROM departments
            WHERE id = %(id)s
            UNION ALL
            SELECT d.*
            FROM departments d
                 INNER JOIN cte ON d.parent_id = cte.external_id
        )
        SELECT * FROM cte;
        """
        cte_query = db_session.query(Department).filter(Department.id.in_(model_ids)).cte(recursive=True, name="result")
        main_alias = aliased(Department, name="L")
        cte_alias = aliased(cte_query, name="R")
        query = cte_query.union_all(db_session.query(main_alias).join(cte_alias, main_alias.parent_id == cte_alias.c.external_id))
        return db_session.query(query).all()


class ExternalUser(Cache):
    __cache__: Dict[str, dict]
    valid_login_names = config.get_config('ctsec.user.login_name', ['th_sysadmin', 'huangwt', 'fanck', 'cpm_admin', 'yaoqc'])

    @classmethod
    def fetch(cls):
        response = requests.get(  # pylint:disable=missing-timeout
            f'{USER_REQUEST_SERVER}/{USER_REQUEST_URI}',
            headers=config.get_config('ctsec.user.headers', {}),
        )
        users = response.json()['data']
        res = {}
        for user in users:
            res[user['loginName'] or ''] = user
        return res

    @classmethod
    def validate(cls, login_name: str) -> bool:
        if not config.get_config('ctsec.user.enable'):
            return True
        if login_name in cls.valid_login_names:
            return True
        cls.load()
        user = cls.get(login_name)
        if not user:
            return False
        if user['userStatus'] != '0':
            return False
        if user['accountStatus'] != '0':
            return False
        return ExternalDepartment.find_by_id(user['deptId'])

    @classmethod
    def get(cls, login_name) -> dict:
        return (cls.__cache__ or {}).get(login_name, {})


@route(r'/ctsec/cas-login')
class UserCasLoginHandler(BaseHandler):
    def get(self, *args, **kwargs):
        ticket = self.get_argument('SSOToken', None)
        base_url = self.origin_host
        origin_url = '{}/api/v1/ctsec/cas-login'.format(base_url)

        if ticket:
            ticket = unquote(ticket)
            token: str = decrypt_ctsec_token(ticket)
            if token is None:
                return self.error('decrypt SSOToken failed')
            user_info = token.split('^')
            if len(user_info) != 3:
                return self.error('token is not valid')
            login_name, code, cname = user_info
            logging.info('<User login_name: %s, code: %s, cname: %s> fetched', login_name, code, cname.strip())
            if not ExternalUser.validate(login_name):
                return self.write('无权限')
            external_user = ExternalUser.get(login_name)
            if not external_user:
                return self.write('用户不存在')
            user = User.make_user(uid=code, ext_uname=external_user['loginName'], username=cname.strip(), **external_user)
            self.session['proxy_user_id'] = str(user.id)
            redirect_url = '{}{}'.format(base_url, config.get_config('cas_auth.cas_after_login'))
        else:
            redirect_url = create_url(
                config.get_config('cas_auth.server'),
                config.get_config('cas_auth.login_uri'),
                ('service', origin_url),
                ('systemName', config.get_config('cas_auth.system_name')),
            )

        logging.debug('Redirecting to: %s', redirect_url)
        return self.redirect(redirect_url)


@route(r'/ctsec/cas-logout')
class UserCasLogoutHandler(BaseHandler):
    def get(self, *args, **kwargs):
        self.clear_all_cookies()
        base_url = self.origin_host
        origin_url = '{}/api/v1/ctsec/cas-login'.format(base_url)
        redirect_url = config.get_config('cas_auth.cas_after_logout')
        if not redirect_url:
            redirect_url = create_url(
                config.get_config('cas_auth.server'),
                config.get_config('cas_auth.logout_uri'),
                (
                    'service',
                    create_url(
                        config.get_config('cas_auth.server'),
                        config.get_config('cas_auth.login_uri'),
                        ('service', origin_url),
                        ('systemName', config.get_config('cas_auth.system_name')),
                    ),
                ),
            )
        logging.debug('Logout, Redirecting to: %s', redirect_url)
        return self.redirect(redirect_url)


@route(r'/ctsec/departments')
class CasDepartmentListHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def get(self, *args, **kwargs):
        records = db_session.query(Department).filter(Department.external_id.isnot(None)).all()
        departments = {}
        record: Department
        for record in records:
            departments[record.external_id] = record.to_dict()

        for record in records:
            parent = departments.get(record.parent_id)
            if parent is None:
                continue
            children = departments[record.external_id]
            children['reserve'] = False
            parent['children'].append(children)
        return self.data([depart for depart in departments.values() if depart.get('reserve', True)])

    @permission_auth([User.P_MANAGE])
    def put(self, *args, **kwargs):
        data = self.get_json_body()
        allow_login = data['allow_login']
        records = ExternalDepartment.find_offsprings(data['ids'])
        depart_ids = [record.id for record in records]
        departments = db_session.query(Department).filter(Department.id.in_(depart_ids)).all()
        res = []
        for department in departments:
            department.allow_login = allow_login
            db_session.add(department)
            res.append(department.to_dict())
        return self.data(res)
