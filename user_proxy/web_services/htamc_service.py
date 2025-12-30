# -*-coding:utf-8-*-
# pylint: disable=too-many-locals,too-many-return-statements,too-many-branches
import logging

from user_proxy.common.custom_dubbo.request import DubboApi
from user_proxy.common.custom_dubbo.util import DubboException
from user_proxy.common.rpc_web_service.web_service_base import WebServiceBase, get_off_redirect_url
from user_proxy.db import db_session
from user_proxy.models.user import User, VisitRecord, VisitSys


class HTAMCWebService(WebServiceBase):
    @classmethod
    def sso_login(
        cls, iv_user, user_id, system, app, ip_address, request_path, project_id, task_id, confirm_tasktype, origin, origin_host, user_name, sys_code, **kwargs
    ):
        if not sys_code:
            return cls.error('miss sysCode', html=True)

        iv_user = iv_user or user_id
        if not iv_user or sys_code not in ('reits', 'atoms'):
            return cls.error('permission denied', html=True)

        logging.info('get iv-user: %s', iv_user)
        # 获取用户数据权限
        try:
            project_data = cls.get_user_data_and_permission(iv_user)
        except DubboException as e:
            return cls.error(f'获取用户数据权限失败: {e.msg}', html=True)

        project_info = {item['dataAssetCode']: item['permission'] for item in project_data}
        _user_name, custom_roles = cls._get_user_info(iv_user)
        user = User.make_user(
            iv_user, iv_user, username=user_name or _user_name or iv_user, custom_system=sys_code, project_info=project_info, custom_roles=custom_roles
        )
        if app:
            if not cls.valid_system_permission(app, user):
                return cls.error('此用户无权限访问', html=True)
            url = get_off_redirect_url(app, user, origin_host=origin_host, origin=origin)
            if not url:
                return cls.error('sys: {} not config'.format(app), html=True)
            return cls.redirect_plus(url, {'user_id': user.id})

        if not ip_address:
            logging.error('x-forwarded-for not set')
        else:
            logging.info('get ip_address: %s', ip_address)
            VisitRecord.create(user.id, VisitSys.TRIDENT.value, api=request_path, ip_address=ip_address)

        url = '/'
        if project_id is not None or task_id is not None:
            if not cls.valid_system_permission('autodoc_overall', user):
                return cls.error('此用户无权限访问', html=True)
            url = get_off_redirect_url(
                system or 'autodoc_overall', user, origin_host=origin_host, projectId=project_id, runId=task_id, confirm_tasktype=confirm_tasktype
            )
            if not url:
                return cls.error('sys: {} not config'.format(system), html=True)
        elif system:
            if not cls.valid_system_permission(system, user):
                return cls.error('此用户无权限访问', html=True)
            url = get_off_redirect_url(system, user, origin_host=origin_host, confirm_tasktype=confirm_tasktype)
            if not url:
                return cls.error('sys: {} not config'.format(system), html=True)
        return cls.redirect_plus(url, {'user_id': user.id})

    @staticmethod
    def is_valid_user(user_id, users):
        return [user for user in users if user_id == user['userId']]

    @staticmethod
    def get_user_data_and_permission(user_id):
        return DubboApi('htamc').request_by_service_key(key='get_user_data_and_permission', params={'userId': user_id}) or []

    @staticmethod
    def list_reits_user():
        return DubboApi('htamc').request_by_service_key('list_reits_user') or []

    @staticmethod
    def list_atoms_user():
        return DubboApi('htamc').request_by_service_key('list_atoms_user') or []

    @classmethod
    def get_user_project_info(cls, ext_uname):
        user = db_session.query(User).filter(User.ext_uname == ext_uname).first()
        if user:
            project_info = user.user_data.get('project_info') or {}
        else:
            # 获取用户数据权限
            try:
                project_data = cls.get_user_data_and_permission(ext_uname)
            except DubboException as e:
                return cls.error(f'获取用户数据权限失败: {e.msg}')
            project_info = {item['dataAssetCode']: item['permission'] for item in project_data}
        return cls.data(project_info)

    @classmethod
    def _get_user_info(cls, iv_user):
        # 获取atoms用户列表
        # 返回的第二个数据为客户方定义的用户role，多个使用’,‘分割
        try:
            atoms_users = cls.list_atoms_user()
            if users := cls.is_valid_user(iv_user, atoms_users):
                return users[0].get('userName'), users[0].get('role', '')
        except DubboException as e:
            logging.error('获取atoms用户列表失败: %s', e.msg)

        # 获取reits用户列表
        try:
            reits_users = cls.list_reits_user()
            if users := cls.is_valid_user(iv_user, reits_users):
                return users[0]['userName'], ''
        except DubboException as e:
            logging.error('获取reits用户列表失败: %s', e.msg)

        return '', ''

    @classmethod
    def get_user_custom_system(cls, iv_user):
        user = db_session.query(User).filter(User.ext_uname == iv_user).first()
        if user:
            return cls.data({"custom_system": user.user_data.get('custom_system')})

        return cls.error('无用户权限')
