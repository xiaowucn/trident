# -*-coding:utf-8-*-
import logging
from urllib.parse import urljoin

import requests
from utensils.auth.token import encode_url

from user_proxy import config
from user_proxy.models.user import User
from user_proxy.utils.lock_task import lock_task
from user_proxy.web_services.htamc_service import HTAMCWebService
from user_proxy.worker.app import app


def push_users_to_sub_system(atoms_users, reits_users):
    atoms_users_data = [{'userId': atoms_user['userId'], 'userName': atoms_user['userName'], 'user_list_system': 'atoms'} for atoms_user in atoms_users]

    atoms_user_ids = {user['userId'] for user in atoms_users}
    both_sys_users, only_reits_users = [], []
    for reits_user in reits_users:
        if reits_user['userId'] in atoms_user_ids:
            both_sys_users.append({'userId': reits_user['userId'], 'userName': reits_user['userName'], 'user_list_system': 'atoms&reits'})
        else:
            only_reits_users.append({'userId': reits_user['userId'], 'userName': reits_user['userName'], 'user_list_system': 'reits'})

    calliper_user_data = atoms_users_data + both_sys_users + only_reits_users

    for sub_sys in ['autodoc_overall', 'glazer', 'calliper']:
        target = config.get_config(f'unify_auth.auth_config.auth_{sub_sys}')
        if not target:
            logging.error("unify_auth sub_sys: %s not config", sub_sys)
            continue
        push_url = urljoin(urljoin(target['internal_host'], target['subpath']), target['push_users_api'])
        url = encode_url(push_url, target['app_id'], target['secret_key'], exclude_domain=True)
        if sub_sys in ['autodoc_overall', 'glazer']:
            json_data = atoms_users_data
        else:
            json_data = calliper_user_data
        try:
            logging.info('push users url: %s', url)
            res = requests.post(url, json=json_data, timeout=config.get_config('worker.timeout', 30), verify=False)
            if res.status_code == 200:
                logging.info('push user to sub system success: %s', res.text)
            else:
                logging.error('push user to sub system failed: %s, status_code: %s', res.text, res.status_code)
        except Exception as e:
            logging.exception(e)


@app.task
@lock_task('htamc_sync_users', exp=600)
def sync_dubbo_users():
    try:
        atoms_users = HTAMCWebService.list_atoms_user()
        reits_users = HTAMCWebService.list_reits_user()
    except Exception as e:
        logging.exception(e)
        return
    logging.debug('atoms users: %s, data: %s', len(atoms_users), atoms_users)
    logging.debug('reits users: %s, data: %s', len(reits_users), reits_users)
    logging.info('start save user')
    for user in atoms_users + reits_users:
        User.make_user(user['userId'], user['userId'], username=user['userName'])
    logging.info('end save user')

    logging.info('start push users to sub_system')
    push_users_to_sub_system(atoms_users, reits_users)
    logging.info('end push users to sub_system')


if __name__ == '__main__':
    sync_dubbo_users()
