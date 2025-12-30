import json
import sys

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.models.user import User, Role


def load_vip_users(path):
    vip_users = json.load(open(path))
    vip_role = db_session.query(Role).filter(Role.name == Role.vip_user).first()
    if not vip_role:
        print('vip role not found')
        return
    exist_users = []
    for user in vip_users:
        db_user = db_session.query(User).filter(User.ext_uname == user['username']).first()
        if db_user:
            exist_users.append(db_user)
            continue
        created_user = User(
            ext_uname=user['username'], password=user['password'], password_salt=user['password_salt']
        )
        created_user.user_data = {
            'uid': user['username'],
            'ext_uname': user['username'],
            'ext_sys': config.get_config('sys'),
            'username': user['username'],
            '_from': config.get_config('sys')
        }
        created_user.roles = [vip_role]
        db_session.add(created_user)
    db_session.commit()
    for user in exist_users:
        print('-'*30)
        print('username: {} already exists'.format(user.ext_uname))


if __name__ == '__main__':
    path = sys.argv[1]
    load_vip_users(path)
