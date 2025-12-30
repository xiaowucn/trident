import base64
import logging
import subprocess

import rsa
from Crypto.PublicKey import RSA

from user_proxy import config


def rsa_encrypt_by_public_key(public_key: str, auth_str: str):
    project_root = config.project_root
    res = subprocess.run(['/usr/bin/java',
                          '-classpath', f'{project_root}/misc/gtja/rsautil-client-1.0-SNAPSHOT.jar',
                          'com.gtja.rsautil.RSAUtil', auth_str, public_key], stdout=subprocess.PIPE)
    if res.returncode == 0:
        decrypted_token = res.stdout
        return decrypted_token.decode()
    logging.error('shell command execution failed')
    return None


def rsa_encrypt_by_public_key_py(public_key_str, plaintext, length=117):
    public_key_bytes = base64.b64decode(public_key_str.encode('utf-8'))
    key = RSA.import_key(public_key_bytes)
    pub_key = rsa.PublicKey(key.n, key.e)
    plaintext_bytes = plaintext.encode('utf-8')
    logging.info('plaintext length: %s', len(plaintext))
    res = []
    for i in range(0, len(plaintext_bytes), length):
        res.append(rsa.encrypt(plaintext_bytes[i:i + length], pub_key))
    return base64.b64encode(b"".join(res)).decode()


def rsa_decrypt_by_private_key(private_key, cipher, length=128):
    private_key_bytes = base64.b64decode(private_key.encode('utf-8'))
    cipher_bytes = base64.b64decode(cipher.encode('utf-8'))
    key = RSA.import_key(private_key_bytes)
    private_key = rsa.PrivateKey(key.n, key.e, key.d, key.p, key.q)
    logging.info('cipher length: %s', cipher)
    res = []
    for i in range(0, len(cipher_bytes), length):
        res.append(rsa.decrypt(cipher_bytes[i:i + length], private_key))
    return b''.join(res).decode()
