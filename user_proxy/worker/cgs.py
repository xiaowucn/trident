import datetime
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

GROUP_REQUEST_SERVER = config.get_config('cgs.group.server')
GROUP_REQUEST_URI = config.get_config('cgs.group.uri')

USER_REQUEST_SERVER = config.get_config('cgs.user.server')
USER_REQUEST_URI = config.get_config('cgs.user.uri')
APP_ID = config.get_config('cgs.app_id')


def get_groups_data(exists_departments):
    sync_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%m:%S')
    get_groups_url = create_url(urljoin(GROUP_REQUEST_SERVER, GROUP_REQUEST_URI), None)
    logging.info('get groups data url: %s', get_groups_url)
    response = requests.post(
        get_groups_url,
        json={
            'appId': APP_ID,
            'syncTime': sync_time,
        },
    )
    data = response.json()
    assert data.get('code') == '1000', data

    logging.info(' groups data: %s', data)

    for group in data['data']:
        Department(
            external_id=group['id'],
        )
        model = exists_departments.pop(str(group['id']), Department(external_id=str(group['groupNumber'])))
        model.parent_id = group.get('parentid')
        model.name = group['name']
        model.data = model.data or {}
        model.data.update(data)
        flag_modified(model, 'data')

    db_session.commit()


@app.task
def sync_group():
    if not (GROUP_REQUEST_SERVER and GROUP_REQUEST_URI):
        return
    departments = db_session.query(Department).filter(Department.external_id.isnot(None)).all()
    exists_departments: Dict[str, Department] = {depart.external_id: depart for depart in departments}

    get_groups_data(exists_departments)


def get_user_data():
    sync_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%m:%S')
    get_users_url = create_url(urljoin(USER_REQUEST_SERVER, USER_REQUEST_URI), None)
    logging.info('get groups data url: %s', get_users_url)
    response = requests.post(
        get_users_url,
        json={
            'appId': APP_ID,
            'syncTime': sync_time,
        },
    )
    data = response.json()
    assert data.get('code') == '1000', data

    logging.info('users data: %s', data)

    for item in data['data']:
        User.make_user(
            item['userid'],
            item['employeenum'],
            departmentIds=item['departmentIds'],
            username=item['realname'],
            _from='cas',
            status=item['status'],
            phone=item["phone"],
            email=item['email'],
            password=item['password'],
        )
    db_session.commit()


@app.task
def sync_user():
    if not (USER_REQUEST_SERVER and USER_REQUEST_URI):
        return
    get_user_data()
    db_session.commit()


if __name__ == '__main__':
    sync_group()
    sync_user()
