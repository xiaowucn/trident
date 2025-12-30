# -*-coding:utf-8-*-
import csv
import logging
import sys

from sqlalchemy.orm.attributes import flag_modified

from user_proxy.db import db_session
from user_proxy.models.user import User


def build_user_info(file_path, unib_file_path=None):
    csv_reader = csv.reader(open(file_path, 'r', encoding='gbk'))
    user_info = {}
    duplicate_ext_uname = set()
    for user_name, ext_uname, emp_number in csv_reader:
        if ext_uname in user_info:
            duplicate_ext_uname.add(ext_uname)
            continue
        user_info[ext_uname] = {
            "username": user_name,
            "emp_number": emp_number
        }
    user_info = {ext_uname: data for ext_uname, data in user_info.items() if ext_uname not in duplicate_ext_uname}
    logging.info('parse csv res: len: %s, user_info: %s', len(user_info), user_info)

    if unib_file_path:
        csv_reader = csv.DictReader(open(unib_file_path, 'r', encoding='gbk'))
        for row in csv_reader:
            ext_uname = row['emp_number']
            fix_ext_uname = f'10{row["emp_number"]}'
            if ext_uname not in user_info and fix_ext_uname not in user_info:
                user_info[ext_uname] = row
                user_info[fix_ext_uname] = row
                logging.info('un ib user info not found: %s', row)

            if ext_uname in user_info:
                user_info[ext_uname].update(row)
            if fix_ext_uname in user_info:
                user_info[fix_ext_uname].update(row)
    logging.info('update un ib csv res: len: %s, user_info: %s', len(user_info), user_info)
    return user_info


def bath_update_user_info(ib_file_path, unib_file_path=None):
    user_info = build_user_info(ib_file_path, unib_file_path)
    exist_user_map = dict(db_session.query(User.ext_uname, User).filter(User.ext_uname.in_(user_info), User.user_data.op('->>')('ext_sys') != 'self'))
    for ext_uname, user_data in user_info.items():
        if ext_uname not in exist_user_map:
            logging.error('user: %s not existed', ext_uname)
            continue
        user = exist_user_map[ext_uname]
        user.user_data.update(user_data)
        flag_modified(user, 'user_data')
        logging.info('modify user: %s user_data: %s', user.ext_uname, user_data)
    db_session.commit()
    logging.info('batch update ib user info end')


if __name__ == '__main__':
    ib_file_path = sys.argv[1]
    unib_file_path = sys.argv[2] if len(sys.argv) > 2 else None
    bath_update_user_info(ib_file_path, unib_file_path)
    # bath_update_user_info('/opt/PycharmProjects/trident/IBS用户名工号.csv', '/opt/PycharmProjects/trident/离职或非IB人员.csv')
