import hashlib
import base64

import pyDes

from user_proxy import config

DigestAlgorithm = "SHA1"
CryptAlgorithm = "DESede/CBC/PKCS5Padding"
KeyAlgorithm = "DESede"
defaultIV = b'\x01\x02\x03\x04\x05\x06\x07\x08'


def gen_auth_string(ias_id, ias_key, timestamp, return_url):
    origin_auth = ias_id + timestamp + return_url
    auth_digest = generate_digest(origin_auth)
    crypt_string = auth_digest + origin_auth
    string_encrypted = encrypt(crypt_string, ias_key, defaultIV)
    return string_encrypted


def generate_digest(string):
    input_bytes = string.encode('utf-8')
    output = hashlib.sha1(input_bytes).digest()
    return base64.b64encode(output).decode('utf-8')


def encrypt(string, encrypt_key, iv):
    input_bytes = string.encode('utf-8')
    _bytes = bytes.fromhex(encrypt_key)
    des = pyDes.triple_des(_bytes, mode=pyDes.CBC, IV=iv, pad=None, padmode=pyDes.PAD_PKCS5)
    encrypted = des.encrypt(input_bytes, padmode=pyDes.PAD_PKCS5)
    return base64.b64encode(encrypted).decode('utf-8')


def decrypt(string, decrypt_key, iv):
    input_bytes = base64.b64decode(string)
    des = pyDes.triple_des(bytes.fromhex(decrypt_key), mode=pyDes.CBC, IV=iv, pad=None, padmode=pyDes.PAD_PKCS5)
    decrypted = des.decrypt(input_bytes, padmode=pyDes.PAD_PKCS5)
    return decrypted


def validate_from_eac(ias_id, ias_key, timestamp, user_account, result, error_str, auth_str):
    if not ias_id or not timestamp or not user_account or not auth_str:
        return False
    origin_auth = ias_id + timestamp + user_account + result + error_str
    auth_digest = generate_digest(origin_auth)
    to_decrypted_str = auth_digest + origin_auth
    current_auth_string = encrypt(to_decrypted_str, ias_key, defaultIV)
    return current_auth_string == auth_str
