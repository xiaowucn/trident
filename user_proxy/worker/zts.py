import logging
from typing import Dict
from urllib.parse import urljoin

import requests
from sqlalchemy.orm.attributes import flag_modified

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.models.user import Department, User
from user_proxy.utils.cas import create_url
from user_proxy.worker.app import app

GROUP_REQUEST_SERVER = config.get_config('zts.group.server')
GROUP_REQUEST_URI = config.get_config('zts.group.uri')

USER_REQUEST_SERVER = config.get_config('zts.user.server')
USER_REQUEST_URI = config.get_config('zts.user.uri')


def get_page_group_data(page, exists_departments, size=100):
    get_groups_url = create_url(urljoin(GROUP_REQUEST_SERVER, GROUP_REQUEST_URI), None,
                                ("groupType", 1), ("total", True), ('status', 1), ("datasource", "HR"), ("page", page), ("size", size))
    logging.info('get groups data url: %s', get_groups_url)
    response = requests.get(get_groups_url)
    data = response.json()
    logging.info('page: %s , groups data: %s', page, data)

    for group in data['items']:
        if group['datasource'] != 'HR':
            continue
        model = exists_departments.pop(
            str(group['groupNumber']),
            Department(external_id=str(group['groupNumber']))
        )
        if group['parents']:
            parent_id, order = group['parents'].split(':')  # 0109:85,0109:部门的 groupNumber, 85在部门的顺序。
        else:
            parent_id = "-1"
        model.parent_id = parent_id
        model.name = group['groupName']
        model.data = model.data or {}
        model.data.update(group)
        flag_modified(model, 'data')
        db_session.add(model)
        logging.info('add new department groupNumber=%s, name=%s', model.external_id, model.name)

    db_session.commit()
    return data['total'] - page * size, exists_departments


@app.task
def sync_group():
    """
    page Int 第几页
    size int 每页的记录数,默认值为 100
    total boolean 是否返回记录总数
    groupType string 部门类型
    status string 部门是否有效
    datasource String 数据来源,人力的为 HR
    """
    if not (GROUP_REQUEST_SERVER and GROUP_REQUEST_URI):
        return
    departments = db_session.query(Department).filter(Department.external_id.isnot(None)).all()
    exists_departments: Dict[str, Department] = {depart.external_id: depart for depart in departments}

    page = 1
    remain_count, exists_departments = get_page_group_data(page, exists_departments)
    while remain_count > 0:
        page += 1
        remain_count, exists_departments = get_page_group_data(page, exists_departments)

    # 删除不是同步的department
    for model in exists_departments.values():
        logging.info('delete not exist in sync department: groupNumber=%s, name=%s', model.external_id, model.name)
        db_session.delete(model)
    db_session.commit()


def get_page_user_data(page, size=100):
    app_code = config.get_config('zts.app_code')
    get_users_url = create_url(urljoin(USER_REQUEST_SERVER, USER_REQUEST_URI), None,
                               ('status', 1), ("page", page), ("size", size), ("appCode", app_code))
    logging.info('get users data url: %s', get_users_url)
    response = requests.get(get_users_url)
    data = response.json()
    user_names = set()
    for item in data['items']:
        if not item['userName']:
            logging.info('page: %s, not uid user data : %s', page, item)
            continue
        depart_data = item['orgs'].split(':')
        if len(depart_data) != 2:
            logging.info('page: %s, error orgs data: %s', page, item)
            continue
        external_id = depart_data[0]
        logging.info('page: %s, user data : %s', page, item)
        User.make_user(item['userName'], item['userName'], department_id=external_id, username=item['name'], _from='cas', email=item['email'],
                       phone=item["phoneNo"], gender=item['gender'], status=item['status'], job_status=item['jobStatus'], employee_status=item['empStatus'])
        user_names.add(item['userName'])
        logging.info('add user ext_uname=%s, username=%s', item['userName'], item['name'])

    return data['total'] - page * size, user_names


@app.task
def sync_user():
    if not (USER_REQUEST_SERVER and USER_REQUEST_URI):
        return
    db_users = db_session.query(User).filter(User.deleted == 0).all()
    sync_user_names = set()
    page = 1
    remain_count, user_names = get_page_user_data(page)
    sync_user_names = sync_user_names.union(user_names)
    while remain_count > 0:
        page += 1
        remain_count, user_names = get_page_user_data(page)
        sync_user_names = sync_user_names.union(user_names)

    for db_user in db_users:
        if db_user.oa_user and db_user.ext_uname not in sync_user_names:
            logging.info('delete not exist in sync user: ext_uname=%s', db_user.ext_uname)
            db_user.deleted = 1
    db_session.commit()


if __name__ == '__main__':
    sync_group()
    sync_user()
