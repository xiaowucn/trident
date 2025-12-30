# pylint: disable=too-many-locals,too-many-return-statements,too-many-positional-arguments
import base64
import logging
from urllib.parse import urljoin

import requests
from Crypto.Cipher import AES

from user_proxy import config
from user_proxy.common.rpc_web_service.web_service_base import WebServiceBase, get_off_redirect_url
from user_proxy.db import db_session
from user_proxy.models.user import User, VisitRecord, VisitSys


class HTSCWebService(WebServiceBase):
    @classmethod
    def sso_login(cls, user_token, user_id, system, app, ip_address, request_path, project_id, task_id, confirm_tasktype, origin, origin_host, **kwargs):
        if user_token:
            logging.info('user_info_token: %s', user_token)
            secret_key = config.get_config('htsc_auth.secret_key')
            try:
                user_id = cls.darkroom_aes_gcm_decrypt(user_token, secret_key)
            except Exception as e:
                logging.exception(e)
                return cls.error('decrypt user_id error')

        if not user_id:
            return cls.error('permission denied', status_code=400)
        logging.info('get user_id: %s', user_id)
        if user_id.lower().startswith('sx'):
            return cls.redirect('/sx/#/wrongPermissions')
        # 获取部门信息
        department = department_id = None
        if config.get_config('htsc_auth.department_enable', False):
            # 判断用户是否内置用户，不是内置的再获取部门信息
            user = db_session.query(User).filter(User.ext_uname == user_id, User.deleted == 0).first()
            if not user or all(role.oa_default for role in user.roles):
                auth_host = config.get_config('htsc_auth.department_host')
                auth_api = config.get_config('htsc_auth.department_api')
                auth_url = urljoin(auth_host, auth_api)
                try:
                    res = requests.post(auth_url, json={"userId": user_id}, timeout=(5, 20))
                    if res.status_code != 200:
                        return cls.error('get department info error, status_code = {}'.format(res.status_code))
                    department_data = res.json()
                    department = department_data['orgName']
                    department_id = department_data['orgId']
                except Exception as e:
                    logging.exception(e)
                    return cls.error('get department error', status_code=400)
                logging.info('get department_id: %s, department: %s', department_id, department)

        user = User.make_user(user_id, user_id, username=user_id, department=department, department_id=department_id)
        if app == 'autodoc_overall':
            url = get_off_redirect_url(app, user, origin_host=origin_host, origin=origin)
            if not url:
                return cls.error('sys: {} not config'.format(app))
            return cls.redirect_plus(url, {'user_id': user.id})

        if not ip_address:
            logging.error('x-forwarded-for not set')
        else:
            logging.info('get ip_address: %s', ip_address)
            VisitRecord.create(user.id, VisitSys.TRIDENT.value, api=request_path, ip_address=ip_address)
        url = '/'
        if project_id is not None or task_id is not None:
            url = get_off_redirect_url(
                system or 'autodoc_overall', user, origin_host=origin_host, projectId=project_id, runId=task_id, confirm_tasktype=confirm_tasktype
            )
            if not url:
                return cls.error('sys: {} not config'.format(system))
        elif system:
            url = get_off_redirect_url(system, user, origin_host=origin_host, confirm_tasktype=confirm_tasktype)
            if not url:
                return cls.error('sys: {} not config'.format(system))
        return cls.redirect_plus(origin or url, {'user_id': user.id})

    @classmethod
    def get_visit_records(cls):
        records = db_session.query(VisitRecord).filter(VisitRecord.ip_address.isnot(None)).order_by(VisitRecord.created_utc.desc())
        return cls.data([record.to_dict() for record in records])

    @classmethod
    def darkroom_sso_login(cls, user_token, system, ip_address, request_path, origin_host, stage_id, stage_type, origin, cps, **kwargs):
        if not user_token:
            return cls.error('miss user_id header parameter')
        secret_key = config.get_config('htsc_darkroom_auth.secret_key')
        try:
            user_id = cls.darkroom_aes_gcm_decrypt(user_token, secret_key)
        except Exception as e:
            logging.exception(e)
            logging.info('user_info_token: %s', user_token)
            return cls.error('decrypt user_id error')
        user = User.make_user(user_id, user_id, username=user_id)
        if not ip_address:
            logging.error('x-forwarded-for not set')
        else:
            logging.info('get ip_address: %s', ip_address)
            VisitRecord.create(user.id, VisitSys.TRIDENT.value, api=request_path, ip_address=ip_address)
        url = '/'
        if stage_id:
            url = get_off_redirect_url(system or 'darkroom', user, origin_host=origin_host, stageId=stage_id, stageType=stage_type, cps=cps)
            if not url:
                return cls.error('sys: {} not config'.format(system))
        elif system:
            url = get_off_redirect_url(system, user, origin_host=origin_host, origin=origin)
            if not url:
                return cls.error('sys: {} not config'.format(system))
        return cls.redirect_plus(url, {'user_id': user.id})

    @staticmethod
    def darkroom_aes_gcm_decrypt(encrypted, secret_key):
        res_bytes = base64.b64decode(encrypted.encode('utf-8'))
        nonce = res_bytes[:12]
        ciphertext = res_bytes[12:-16]
        auth_tag = res_bytes[-16:]
        aes_cipher = AES.new(str.encode(secret_key), AES.MODE_GCM, nonce)
        return aes_cipher.decrypt_and_verify(ciphertext, auth_tag).decode('utf-8')


if __name__ == '__main__':
    print(HTSCWebService.darkroom_aes_gcm_decrypt("ZhyU7vboWqZEy9rGqo6eBWKjPjVEffzQkeiWtAhssMQhwg==", "eLIB6L2iHjci6xsmSW8pUqoxmGUnYAq8"))
