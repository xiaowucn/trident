# -*-coding:utf-8-*-
# pylint: disable=too-many-locals
import os
import time
import uuid
from collections import defaultdict
from urllib.parse import quote_plus

import jwt
import requests
from invoke import task
from openpyxl.workbook import Workbook

from user_proxy import config
from user_proxy.config import project_root
from user_proxy.db import db_session
from user_proxy.models.user import User


class SignatureUtil:
    @classmethod
    def get_sign(cls, sorted_params):
        content = []
        for key in sorted(sorted_params.keys()):
            value = sorted_params.get(key)
            if cls.are_not_empty([key, value]):
                content.append(f"{quote_plus(key)}={quote_plus(value)}")
        return '&'.join(content)

    @staticmethod
    def are_not_empty(values):
        return all(value and value.strip() for value in values)


def generate_jwt_token():
    app_id = config.get_config('sync_user.app_id')
    app_secret = config.get_config('sync_user.app_secret')
    payload = {'timestamp': str(int(time.time() * 1000)), 'noncestr': str(uuid.uuid4()), 'secretKey': app_secret}

    sign_secret = SignatureUtil.get_sign(payload)
    print(sign_secret)
    payload.pop('secretKey', None)
    payload['aud'] = app_id
    token = jwt.encode(payload, sign_secret, algorithm="HS256")
    print(token)
    return token


def get_page_users(page, size=500):
    sync_user_url = config.get_config('sync_user.sync_user_url')
    token = generate_jwt_token()
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + token}
    body = {"page": page, "size": size, "startTime": ""}
    response = requests.post(sync_user_url, json=body, headers=headers, verify=False)
    data = response.json()
    print(f"total users: {data['data']['total']}")
    return int(data['data']['total']) - page * size, data['data']['list']


def sync_oa_users():
    page = 1
    remain_count, sync_users = get_page_users(page)
    while remain_count > 0:
        page += 1
        remain_count, users = get_page_users(page)
        sync_users.extend(users)
    print(f'sync users length: {len(sync_users)}')
    return sync_users


@task
def export_user_info(ctx):
    sync_users = sync_oa_users()
    deduplicate_users = {item['workNo']: item for item in sync_users}

    users = db_session.query(User).filter(User.deleted == 0).order_by(User.id.desc()).all()
    fix_users = [user for user in users if not user.is_sys_admin and user.oa_user]

    export_users = defaultdict(list)
    checked_users = set()
    for work_no, sync_user in deduplicate_users.items():
        sync_user_info = {sync_user['workNo'], sync_user['userName'], sync_user['adAccount']}
        for user in fix_users:
            if {user.ext_uname, user.user_data['username']} & sync_user_info:
                export_users[work_no].append(user)
                checked_users.add(user.ext_uname)

    duplicate_users = {}
    export_list = [('ID', 'uid', '_from', 'bu_name', 'ext_sys', 'username', 'ext_uname', 'department', 'department_id', 'workNo', 'adAccount', 'userName')]
    # 匹配一个数据
    for work_no, matched_users in export_users.items():
        if len(matched_users) != 1:
            duplicate_users[work_no] = matched_users
            continue
        export_list.append(
            (
                matched_users[0].id,
                matched_users[0].user_data['uid'],
                matched_users[0].user_data['_from'],
                matched_users[0].user_data.get('bu_name'),
                matched_users[0].user_data['ext_sys'],
                matched_users[0].user_data['username'],
                matched_users[0].ext_uname,
                matched_users[0].user_data.get('department'),
                matched_users[0].user_data.get('department_id'),
                work_no,
                deduplicate_users[work_no]['adAccount'],
                deduplicate_users[work_no]['userName'],
            )
        )
    # 未匹配数据
    for user in fix_users:
        if user.ext_uname not in checked_users:
            export_list.append(
                (
                    user.id,
                    user.user_data['uid'],
                    user.user_data['_from'],
                    user.user_data.get('bu_name'),
                    user.user_data['ext_sys'],
                    user.user_data['username'],
                    user.ext_uname,
                    user.user_data.get('department'),
                    user.user_data.get('department_id'),
                    '',
                    '',
                    '',
                )
            )

    # 匹配多个数据
    for work_no, duplicate_user_list in duplicate_users.items():
        for duplicate_user in duplicate_user_list:
            export_list.append(
                (
                    duplicate_user.id,
                    duplicate_user.user_data['uid'],
                    duplicate_user.user_data['_from'],
                    duplicate_user.user_data.get('bu_name'),
                    duplicate_user.user_data['ext_sys'],
                    duplicate_user.user_data['username'],
                    duplicate_user.ext_uname,
                    duplicate_user.user_data.get('department'),
                    duplicate_user.user_data.get('department_id'),
                    work_no,
                    deduplicate_users[work_no]['adAccount'],
                    deduplicate_users[work_no]['userName'],
                )
            )

    workbook = Workbook()
    worksheet = workbook.worksheets[0]
    for row_index, rows in enumerate(export_list, start=1):
        for col_index, cell_text in enumerate(rows, start=1):
            if cell_text:
                worksheet.cell(row_index, col_index, cell_text)
    workbook.save(os.path.join(project_root, 'data', 'export_users.xlsx'))
