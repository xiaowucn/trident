# -*-coding:utf-8-*-
import datetime
import hashlib
import hmac

from user_proxy import config


def generate_request_date():
    return datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def generate_signature(sign_str):
    secret_key = config.get_config('swhysc_auth.demeter_secret_key')
    hmac_sha256 = hmac.new(secret_key.encode(), sign_str.encode(), digestmod=hashlib.sha256)
    ret = hmac_sha256.hexdigest()
    return ret
