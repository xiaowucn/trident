import json
import logging
import os
import urllib
from urllib.parse import urljoin

from suds import sudsobject

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.handlers.base import route, BaseHandler, permission_auth
from user_proxy.models.user import User, Department
from user_proxy.suds_client import get_suds_client


def process_suds_location(url):
    if url.endswith('?wsdl'):
        return url[:-5]
    return url


@route(r'/cjsc/project-types')
class CJSCProjectTypeHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def get(self, *args, **kwargs):
        """
        :param args:
        :param kwargs:
        :return: [{"proTypeId": project_type_id, "proTypeName": project_type_name}]
        """
        # 业务管理员
        if self.current_user.is_super_admin:
            project_types_data = self.current_user.business_project_types
            return self.data(
                [{"proTypeId": project_type_id, "proTypeName": project_type_name} for project_type_id, project_type_name in project_types_data.items()])

        # for test
        if config.get_config('customer_uri_info.debug'):
            file_path = os.path.join(config.project_root, 'data/cjsc_data/project_types.json')
            data = json.load(open(file_path))
            return self.data(data)

        base_url = config.get_config('customer_uri_info.base_server')
        project_type_uri = config.get_config('customer_uri_info.get_project_type_uri')
        project_type_url = urllib.parse.urljoin(base_url, project_type_uri)
        try:
            client = get_suds_client(project_type_url)
            service = client.service
            project_type_data = service.getProjectType()
        except ConnectionError as e:
            logging.error('can not connect web service: {}'.format(e))
            return self.error('can not connect web service')

        project_type_dict = sudsobject.asdict(project_type_data)
        return_state = project_type_dict.get('returnState')
        project_type_list = project_type_dict.get('message')
        if return_state != 2:
            logging.error('parse project_type info error, returnState=%s, message=%s', return_state, project_type_list)
            return self.error('parse project_type info error')
        if isinstance(project_type_list, str):
            project_type_list = json.loads(project_type_list)
        return self.data(project_type_list)


@route(r'/cjsc/departments')
class DepartmentHandler(BaseHandler):

    @permission_auth([User.P_MANAGE])
    def get(self, *args, **kwargs):
        """
        :param args:
        :param kwargs:
        :return: [{"department_id": "部门id", "department_name": "部门名称", "deleted": 0}]
        """
        cond = Department.external_id.isnot(None)
        if self.current_user.is_super_admin:
            department_ids = list(self.current_user.business_departments.keys())
            cond &= Department.external_id.in_(department_ids)
        records = db_session.query(Department).filter(cond).all()
        departments_data = []
        for record in records:
            departments = Department.find_departments_by_external_id(record.external_id)
            display_department = '-'.join(department.name for department in departments[::-1])
            departments_data.append({
                "department_id": record.external_id,
                "department_name": record.name,
                'deleted': record.deleted,
                'display_department': display_department,
            })
        return self.data(departments_data)
