import json
import logging

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.models.user import Role


def get_department_roles(first_level_department_id, default_role):
    user_roles = []
    department_role_ids = config.get_config('sync_user_info.department_roles.first_level.department_ids', [])
    if isinstance(department_role_ids, str):
        department_role_ids = json.loads(department_role_ids)
    if first_level_department_id in department_role_ids:
        role_names = config.get_config('sync_user_info.department_roles.first_level.default_roles')
        if isinstance(role_names, str):
            role_names = json.loads(role_names)
        user_roles = db_session.query(Role).filter(Role.name.in_(role_names)).all()
    elif default_role:
        user_roles = [default_role]
    return user_roles


def get_department_info(department_result):
    department_datas = {}
    for department_data in department_result:
        department_info = {}
        department_id = department_data.get('_departmentid')
        if department_id is None:
            logging.info('department: %s, departmentid is None', department_data.get('_fullname', ''))
            continue
        department_info['department_id'] = int(department_id)
        department_info['full_name'] = department_data.get('_fullname', '')
        department_info['short_name'] = department_data.get('_shortname', '')
        supper_department_id = department_data.get('_supdepartmentid')
        if supper_department_id is None:
            logging.info('department: %s, _supdepartmentid is None', department_data.get('_fullname', ''))
            continue
        department_info['supper_department_id'] = int(supper_department_id)
        department_datas[int(department_id)] = department_info

    total_department_info = _build_department_tree(department_datas)

    return total_department_info


def get_user_info(user_result):
    user_datas = {}
    for user_data in user_result:
        user_info = {}
        uid = user_data.get('loginid', '')
        if not uid:
            logging.info('user: %s do not have loginid', user_data.get('lastname', ''))
            continue
        user_info['department'] = user_data.get('departmentname', '')
        department_id = user_data.get('departmentid')
        if department_id is not None:
            user_info['department_id'] = int(department_id)
        user_info['username'] = user_data.get('lastname', '')
        work_status = user_data.get('status')
        if work_status is not None:
            user_info['work_status'] = int(work_status)
        user_datas[uid] = user_info
    return user_datas


def _build_department_tree(department_datas):
    root = RootDepartmentTree(index=0)
    # logging.info('department_datas: {}'.format(department_datas))
    for index, department_info in department_datas.items():
        department_datas[index] = SubDepartmentTree(**department_info)

    for department in department_datas.values():
        # 本部门即为一级部门
        if department.parent_id == 0:
            department.first_level_department_id = department.index

    for department in department_datas.values():
        parent_id = department.parent_id
        # 本部门即为一级部门
        if parent_id == 0:
            continue
        # 未找到上级部门
        parent = department_datas.get(parent_id, root)
        if parent.index == 0:
            logging.info('can not find parent in department_datas, parent_id: %s', parent_id)
            continue
        if parent.first_level_department_id is not None:
            department.first_level_department_id = parent.first_level_department_id
            continue

        while parent.parent_id != 0 and parent.first_level_department_id is None:
            parent = department_datas.get(parent.parent_id, root)
            # 未找到上级部门
            if parent.index == 0:
                logging.info('can not find parent in department_datas, parent_id: %s', parent_id)
                break
            if parent.parent_id == 0:
                department.first_level_department_id = parent.index
                break
            if parent.first_level_department_id is not None:
                department.first_level_department_id = parent.first_level_department_id
                break

    return department_datas


class RootDepartmentTree(object):
    def __init__(self, index, **kwargs):
        self.index = index


class SubDepartmentTree(RootDepartmentTree):
    def __init__(self, department_id, supper_department_id, full_name, short_name, **kwargs):
        super(SubDepartmentTree, self).__init__(department_id, **kwargs)
        self.parent_id = supper_department_id
        self.full_name = full_name
        self.short_name = short_name
        self.first_level_department_id = None


if __name__ == '__main__':
    from user_proxy.worker.kysec import sync_user_data_from_customer_db

    sync_user_data_from_customer_db()
