# -*-coding:utf-8-*-
import logging
import os
import json

import jwt
from jwcrypto import jwe
from jwcrypto.jwk import JWK
from jwt import PyJWK
from jwt.algorithms import RSAAlgorithm
from jwt.utils import force_bytes
from utensils.util import generate_timestamp

from user_proxy import config


def get_user_info(id_token, key_data: [str, dict], audience, from_json=False):
    """
    :param id_token:
    :param key_data:
    :param from_json:
    :return: {'email': 'guohong@nesc.cn', 'name': '郭东北', 'mobile': '18911902588', 'externalId': '1593', 'udAccountUuid': '0246474571502dd114154e8e36a12de5BeSck7LUWNX', 'ouId': '102', 'ouName': '业务管理部', 'openId': None, 'idpUsername': '1593', 'username': '1593', 'applicationName': '投行智能复核系统', 'enterpriseId': 'test', 'instanceId': 'test', 'aliyunDomain': '', 'extendFields': {}, 'exp': 1656038628, 'jti': 'b7poTCeGOe1on2rySq_VkQ', 'iat': 1656038028, 'nbf': 1656037968, 'sub': '1593', 'iss': 'http://10.211.96.22:38776/', 'aud': 'testplugin_jwt161'}
    """
    try:
        if isinstance(key_data, dict):
            py_jwk = PyJWK.from_dict(key_data)
            public_key = py_jwk.key
        else:
            with open(key_data, 'r') as open_file:
                public_key = open_file.read()
            if from_json:
                py_jwk = PyJWK.from_json(public_key)
                public_key = py_jwk.key
            else:
                algo = RSAAlgorithm(RSAAlgorithm.SHA256)
                public_key = algo.prepare_key(public_key)
        token_info = jwt.decode(force_bytes(id_token), key=public_key, verify=True, algorithms=['RS256'], audience=audience)
        user_info = json.loads(json.dumps(token_info))
    except Exception as e:
        logging.exception(e)
    else:
        return user_info


def encrypt_user_info(data):
    try:
        algo = RSAAlgorithm(RSAAlgorithm.SHA256)
        key_path = os.path.join(config.project_root, 'data/keys/private.pem')
        pem_key = open(key_path, 'r')
        private_key = algo.prepare_key(pem_key.read())
        token = jwt.encode(data, private_key, algorithm='RS256')
        return token
    except Exception as e:
        print(e)


def jwe_encode(payload: dict, jwk: JWK, *, expire_seconds: int = None) -> str:
    """
    Encrypt payload using JWE (JSON Web Encryption) with jwcrypto
    """
    now = generate_timestamp()
    payload["iat"] = now
    if expire_seconds:
        payload["exp"] = now + expire_seconds

    payload_str = json.dumps(payload)

    jwe_token = jwe.JWE(plaintext=payload_str.encode('utf-8'), protected={"alg": jwk["alg"], "enc": "A256GCM", "typ": "JWE", "kid": jwk.get('kid')})

    jwe_token.add_recipient(jwk)
    return jwe_token.serialize(compact=True)


def jwe_decode(token: str, jwk: JWK) -> dict:
    """
    Decrypt JWE token using jwcrypto
    """
    jwe_token = jwe.JWE()
    jwe_token.deserialize(token)

    jwe_token.decrypt(jwk)

    payload_str = jwe_token.payload.decode('utf-8')
    return json.loads(payload_str)


if __name__ == '__main__':
    # _token = encrypt_user_info({'username': 'lixiaolong'})
    _token = 'eyJhbGciOiJSUzI1NiIsImtpZCI6Ijg3MTQ4ODI3Mzg2NTM2NjUyMjkifQ.eyJlbWFpbCI6Imd1b2hvbmdAbmVzYy5jbiIsIm5hbWUiOiLpg63kuJzljJciLCJtb2JpbGUiOiIxODkxMTkwMjU4OCIsImV4dGVybmFsSWQiOiIxNTkzIiwidWRBY2NvdW50VXVpZCI6IjAyNDY0NzQ1NzE1MDJkZDExNDE1NGU4ZTM2YTEyZGU1QmVTY2s3TFVXTlgiLCJvdUlkIjoiMTAyIiwib3VOYW1lIjoi5Lia5Yqh566h55CG6YOoIiwib3BlbklkIjpudWxsLCJpZHBVc2VybmFtZSI6IjE1OTMiLCJ1c2VybmFtZSI6IjE1OTMiLCJhcHBsaWNhdGlvbk5hbWUiOiLmipXooYzmmbrog73lpI3moLjns7vnu58iLCJlbnRlcnByaXNlSWQiOiJ0ZXN0IiwiaW5zdGFuY2VJZCI6InRlc3QiLCJhbGl5dW5Eb21haW4iOiIiLCJleHRlbmRGaWVsZHMiOnt9LCJleHAiOjE2NTYwMzg2MjgsImp0aSI6ImI3cG9UQ2VHT2Uxb24ycnlTcV9Wa1EiLCJpYXQiOjE2NTYwMzgwMjgsIm5iZiI6MTY1NjAzNzk2OCwic3ViIjoiMTU5MyIsImlzcyI6Imh0dHA6Ly8xMC4yMTEuOTYuMjI6Mzg3NzYvIiwiYXVkIjoidGVzdHBsdWdpbl9qd3QxNjEifQ.sH7OM_UEXsJt_MsEqGMPkPCGIb8ZB6Gzq4N-dYadDCHZ_FLEsTJHq3FmzjxiMy_fgAcah3QHhm2YSzA-KLoUc8B8RVgOpeUDll8FIBKGw0R3PqFoVoKKb9yv2qSagcupWAOkE9eRf64n9OAjSx8kEewq72ig0vAa6YxK49F5YDeXek6MX2UV0Lkq-yaKWNoXTjp1IpFTW2yD8ZLq8aibC7s9izp_QvVCZrpnPW3PlCLqtN-5rCeiSrnS8j32Pb4Jq_1pg1S7ojECVmt6MveMGBgt1eXiix449cZCv060R6jf8JaN6X2j7mzvZdkTqXBigwc9_p5D6IBo6w-CPiKcew'
    # key_info = {"kty": "RSA", "kid": "8714882738653665229", "alg": "RS256", "n": "tO-g1X7tLv7m5JJoItPnOM_brk0bZSAMEeZMDa12b2ZkLedNuN1sD9Zk2NYCyDsvW8vl4ZNlYWNZAPr3pccIEqv1cq6GbkAJHqb9aIp41diFqS2AqbYn_HuvZUmISX1bQXEeFDdFciR6j8npBQGoFwVjkkoVCEIlSpk1ebcltT2QwF81whyyVfiBlGMX1EidVCtD5dNF7yGBGduIw9wRhrO-2hEhu8K8Y_rDu-E9Z9f_6iYQRzZDrusdzCKpE5AxYbeqjZcV_XvuX-WsKD_GDgb6n9ApWeb2PK5QbV-cMeUA0yowOgiD2-brwtgjyWemQNk_8tU-FliVZYH7OoaFuQ", "e": "AQAB"}
    key_info = os.path.join(config.project_root, config.get_config("jwt_auth.key_path", 'data/keys/cjsc_test_rsa_public_key.json'))
    app_id = config.get_config('jwt_auth.app_id')
    get_user_info(_token, key_info, audience=app_id, from_json=True)
