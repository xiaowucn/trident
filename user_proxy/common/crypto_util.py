import base64
import json
import sys
import zlib
from binascii import a2b_hex

from Crypto.Cipher import AES
from Crypto.Util import Counter


def aes_encrypt(plaintext, key, fill=False, test=True):
    if test:
        passed = aes_encrypt_test()
        if not passed:
            sys.exit(1)
    else:
        passed = True
    key = key.encode('utf8')
    blocksize = 16
    reminder_len = len(plaintext) % blocksize
    reminder = b''
    if reminder_len > 0:
        if fill:
            plaintext += b'\0' * (blocksize - reminder_len)
        else:
            plaintext, reminder = plaintext[:-reminder_len], plaintext[-reminder_len:]
    aes = AES.new(key, AES.MODE_CBC, key[11:27])
    return aes.encrypt(plaintext) + reminder if passed else b""


def aes_encrypt_test():
    plaintext = b"this is plaintext."
    expectedtext = "B2tf/oy8SGl1PWonFpku3aEMoGl1q4Uw24B0VX96L24=\n"
    ciphertext = base64.encodebytes(aes_encrypt(plaintext, key="#hello-aes-hello-aes-hello-aes##", fill=True, test=False))
    return expectedtext == ciphertext.decode()


def aes_decrypt(ciphertext, key, strip=False):
    key = key.encode('utf8')
    blocksize = 16
    reminder_len = len(ciphertext) % blocksize
    if not strip and reminder_len > 0:
        ciphertext, reminder = ciphertext[:-reminder_len], ciphertext[-reminder_len:]
    else:
        reminder = b''
    aes = AES.new(key, AES.MODE_CBC, key[11:27])

    if strip:
        return aes.decrypt(ciphertext).rstrip(b'\0')
    return aes.decrypt(ciphertext) + reminder


def aes_ctr_decrypt(ciphertext, key, iv):
    ciphertext = a2b_hex(ciphertext)
    ctr = Counter.new(128, initial_value=int.from_bytes(iv.encode(), 'big'))

    aes = AES.new(key.encode('utf8'), AES.MODE_CTR, counter=ctr)
    plaintext = aes.decrypt(ciphertext)
    return plaintext.rstrip(b'\0').decode('utf-8')


class PackageEncrypt(object):
    def __init__(self, key):
        self.secret_key = key[:16].ljust(16, '\0').encode()
        self.iv_key = key[::-1][:16].ljust(16, '\0').encode()

    def encrypt(self, data):
        data = zlib.compress(data)
        aes = AES.new(self.secret_key, AES.MODE_CBC, self.iv_key)
        padding_size = 16 - (len(data) + 1) % 16
        if padding_size == 16:
            padding_size = 0
        data = b"%s%s" % (hex(padding_size)[2:].encode(), data)
        if padding_size:
            data = data.ljust(len(data) + padding_size, b'\0')
        return aes.encrypt(data)

    def encrypt_json(self, json_data):
        str_data = json.dumps(json_data).encode('utf-8')
        return self.encrypt(str_data)

    def decrypt(self, data):
        if isinstance(data, str):
            data = data.encode()
        aes = AES.new(self.secret_key, AES.MODE_CBC, self.iv_key)
        data = aes.decrypt(data)
        padding_size = int(chr(data[0]), 16)
        data = data[1:]
        if padding_size:
            data = data[:-padding_size]
        data = zlib.decompress(data)
        return data.decode()

    def decrypt_json(self, data):
        return json.loads(self.decrypt(data))
