# -*- coding:utf-8 -*-
# CYC: skip-file
import os
import traceback
import requests
import sys

if os.getenv('PSYCOPG2_GAUSS', '').lower() == 'true':
    sys.path.insert(0, "/usr/lib/paoding/dist-packages")


def check_supervisor():
    try:
        import supervisor.xmlrpc
        from xmlrpc.client import ServerProxy

        proxy = ServerProxy('http://127.0.0.1',
                            transport=supervisor.xmlrpc.SupervisorTransport(
                                None, None, serverurl='unix:///dev/shm/supervisor.sock'))

        for status in proxy.supervisor.getAllProcessInfo():
            assert status['statename'] == 'RUNNING'
    except:
        print(traceback.print_exc())
        os.sys.exit(1)


def check_url_status(url, status_code=200):
    try:
        request_status_code = requests.get(url, headers={'User-agent': 'Chrome'}, timeout=0.5).status_code
        assert request_status_code == status_code
    except:
        print('url: {} status code is {}, not {}'.format(url, request_status_code, status_code))
        os.sys.exit(1)


def check_pg():
    if "API" == os.environ.get('MODE'):
        return
    from user_proxy.db import db_session
    try:
        assert len(db_session.execute('SELECT version_num FROM alembic_version').fetchall()) != 0
    except:
        print('postgresql not connected')
        os.sys.exit(1)


def check_nginx_and_api():
    if "SERVICE" == os.environ.get('MODE'):
        return
    check_url_status('http://127.0.0.1:8080/index.html')
    check_url_status('http://127.0.0.1:8080/api/v1/test')


def check():
    check_supervisor()
    check_pg()
    check_nginx_and_api()


if __name__ == "__main__":
    check()
