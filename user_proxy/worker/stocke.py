# -*-coding:utf-8-*-
# pylint: disable=too-many-locals
import logging
from collections import defaultdict

from pyhive import hive
from sqlalchemy.orm.attributes import flag_modified

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.models.user import User, CustomerSysConfig, Department
from user_proxy.session import RedisDriver
from user_proxy.utils.authtoken import generate_timestamp
from user_proxy.worker.app import app

STOCKE_LOCK_KEY = 'stocke_sync_user_info'


def get_connect():
    host = config.get_config('stocke_sync.hive.host')
    port = config.get_config('stocke_sync.hive.port')
    username = config.get_config('stocke_sync.hive.username') or None
    password = config.get_config('stocke_sync.hive.password') or None
    db_name = config.get_config('stocke_sync.hive.db_name')
    auth = "CUSTOM" if password else None
    return hive.connect(host=host, port=port, username=username, password=password, database=db_name, auth=auth)


def sync_dept_info():
    connect = get_connect()
    dept_sql = config.get_config('stocke_sync.dept_sql')
    with connect as conn:
        cursor = conn.cursor()
        cursor.execute(dept_sql)
        sync_departments = cursor.fetchall()
        logging.info('sync total departments: %s', len(sync_departments))

        db_department_map = dict(db_session.query(Department.external_id, Department).all())
        for sync_dept in sync_departments:
            external_id, name, parent_id = sync_dept[0], sync_dept[1], sync_dept[2]
            dept = db_department_map.pop(external_id, Department(external_id=external_id))
            dept.name = name
            dept.parent_id = parent_id
            dept.deleted = 0
            db_session.add(dept)
        for external_id, dept in db_department_map.items():
            logging.info('delete not exist in sync depts: dept_id=%s, dept_name=%s', external_id, dept.name)
            dept.deleted = 1
        db_session.commit()
        cursor.close()


def get_need_sync_user_map():
    dept_id_str = config.get_config('stocke_sync.dept_ids') or ''
    config_dept_ids = [item for item in dept_id_str.split(',') if item]

    all_departments = []
    for dept_id in config_dept_ids:
        all_departments.extend(Department.find_departments_by_external_id(dept_id, find_parent=False))
    dept_ids = {dept.external_id for dept in all_departments if dept.deleted == 0}
    if not dept_ids:
        return {}

    connect = get_connect()
    dept_sql = config.get_config('stocke_sync.dept_user_sql')
    with connect as conn:
        cursor = conn.cursor()
        cursor.execute(dept_sql, {'dept_ids': tuple(dept_ids)})
        user_id_dept_map = {item[0]: item[1] for item in cursor.fetchall()}
        cursor.close()
    return user_id_dept_map


@app.task
def sync_user_data_from_customer_db():
    redis_driver = RedisDriver()
    if not redis_driver.client.set(STOCKE_LOCK_KEY, generate_timestamp(), 3600, nx=True):
        return
    customer_config = db_session.query(CustomerSysConfig).first()
    if not customer_config or not customer_config.sync_user:
        redis_driver.client.delete(STOCKE_LOCK_KEY)
        return

    # 同步所有部门信息
    sync_dept_info()
    # 根据配置的部门id，筛选需要同步的user_id
    need_sync_users = get_need_sync_user_map()
    if not need_sync_users:
        redis_driver.client.delete(STOCKE_LOCK_KEY)
        return

    user_sql = config.get_config('stocke_sync.user_sql')
    exist_users = dict(db_session.query(User.ext_uname, User))
    exist_department_map = dict(db_session.query(Department.external_id, Department.name))
    connect = get_connect()
    with connect as conn:
        cursor = conn.cursor()
        cursor.execute(user_sql, {"user_ids": tuple(need_sync_users.keys())})
        sync_users = cursor.fetchall()
        logging.info('sync total users: %s', len(sync_users))
        cursor.close()

    group_users = defaultdict(list)
    for item in sync_users:
        group_users[item[0]].append(item)

    valid_users = [sorted(items, key=lambda x: x[-1], reverse=True)[0] for items in group_users.values()]
    logging.info('valid users: %s', len(valid_users))
    for user_id, user_account, user_name, email, mobile, _ in valid_users:
        user = exist_users.pop(user_account, None)
        user_data = {
            'work_status': 1,
            'department_id': need_sync_users[user_id],
            'department': exist_department_map[need_sync_users[user_id]],
            'email': email,
        }
        if user and user.deleted:
            user_data['allow_login'] = False
        new_user = User.make_user(user_id, user_account, username=user_name, **user_data)
        if not user or not user.password:
            new_user.set_password(f"Zszqznsh{str(mobile or '')[-4:]}!")

    if customer_config.disable_former_employee:
        for user in exist_users.values():
            if user.is_sys_admin:
                continue
            user.user_data.update({"work_status": 2, 'allow_login': False})
            flag_modified(user, 'user_data')
    db_session.commit()

    redis_driver.client.delete(STOCKE_LOCK_KEY)


if __name__ == '__main__':
    sync_user_data_from_customer_db()
