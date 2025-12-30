# -*-coding:utf-8-*-


import binascii

from gmssl import sm4


# SM4加密模块
class SM4Util:
    def __init__(self):
        self.crypt_sm4 = sm4.CryptSM4()

    @staticmethod
    def str_to_hex_str(hex_str):
        """
        字符串转hex
        :param hex_str: 字符串
        :return: hex
        """
        hex_data = hex_str.encode('utf-8')
        str_bin = binascii.unhexlify(hex_data)
        return str_bin

    def encrypt_sm4(self, encrypt_key, value: str, mode: str = "ECB", iv: str = None):
        """
        sm4加密
        :param encrypt_key: sm4加密key
        :param value: 待加密的字符串
        :param mode: 模式，CBC or ECB
        :param iv: 偏移量（ECB模式没有偏移量）
        :return: sm4加密后的十六进制值
        """
        if isinstance(encrypt_key, str):
            encrypt_key = self.str_to_hex_str(encrypt_key)

        crypt_sm4 = self.crypt_sm4
        crypt_sm4.set_key(encrypt_key, sm4.SM4_ENCRYPT)  # 设置密钥
        bytes_data = value.encode('utf-8')
        if mode == "ECB":
            encrypt_value = crypt_sm4.crypt_ecb(bytes_data)
        else:
            assert iv, 'CBC mode must set iv'
            encrypt_value = crypt_sm4.crypt_cbc(iv.encode('utf-8'), bytes_data)
        return encrypt_value.hex()

    def decrypt_sm4(self, decrypt_key, encrypt_value: str, mode: str = "ECB", iv: str = None):
        """
        sm4解密
        :param decrypt_key:sm4加密key
        :param encrypt_value: 待解密的十六进制值
        :param mode: 模式，CBC or ECB
        :param iv: 偏移量（ECB模式没有偏移量）
        :return: 原字符串
        """
        if isinstance(decrypt_key, str):
            decrypt_key = self.str_to_hex_str(decrypt_key)

        crypt_sm4 = self.crypt_sm4
        crypt_sm4.set_key(decrypt_key, sm4.SM4_DECRYPT)
        if mode == 'ECB':
            decrypt_value = crypt_sm4.crypt_ecb(bytes.fromhex(encrypt_value))
        else:
            assert iv, 'CBC mode must set iv'
            decrypt_value = crypt_sm4.crypt_cbc(iv.encode('utf-8'), bytes.fromhex(encrypt_value))
        return decrypt_value.decode('utf-8')


if __name__ == '__main__':
    import json

    secret_key = "48487d8bb9f8bf8691c114dcee4d0219"
    iv = '1234567891234567'
    sm4_ins = SM4Util()

    # str_data = json.dumps({"user_name":"gyrx-wuhao","accountType":"0","active":True,"userId":"1075","oaEmpNo":"1002","authorities":["cv-form","cv-compare","cv-table"],"client_id":"fcv","realName":"吴皓","oaEmail":"wu.hao02@icbccs.com.cn","domainName":"gyrx-wuhao","oaUserId":"wu.hao02","userType":"3","email":"wu.hao02@icbccs.com.cn"}, ensure_ascii=False)
    # enc_data = sm4_ins.encrypt_sm4(secret_key, str_data, mode='CBC', iv=iv)  # 加密后的数据
    # enc_data = sm4_ins.encrypt_sm4(secret_key, str_data, mode='ECB')  # 加密后的数据
    # print("sm4加密结果：", enc_data)

    enc_data = "88fc71885723dde00dce5153472383fc29e34122f22d9b6af9682940dec9acd38aa5a72d59e7c5c85bde12485caf2233ff632a9f657e79989050042f220c8c8e4589a40b98cfc1a6260438805f9629d383bb5673f45b991e7ad3cf576ee239dc9db59c1dd00219290b79c770ed99d16a67aa1d6aacc279342a73bdeed71429169753e57973773c3b24332fd1b3b7c879b2fb39e112af6883e54933d5e2dcd3248009593ff72a44ffe075c0e2b7f2018a85437b0552747a02d2d4cc94c042c04a0e9b8ab90e48d0ea94e4c7732253e23f14835e8c8afe7fbd633c349c69c53a2343faeca7c37ed14c03df52636ea21f86e17c73cb537c59cab9911944873fcbef02107b5a1224567985f7326757acc54cc104f9ee486ab363a9ed52633a5cbbe10e9b8ab90e48d0ea94e4c7732253e23f5aded1f4621b2bc06d4cd92dcaa0c57c"
    # enc_data = "a92b7dc603584039688afd43208c7bcd01c3954a6a1342879077cf2028d8d13e619e5a5cceead6fa8a2de5c5c8b915d4fbfab3e6dc2ce14b93013bc9f5e66a9247345da67fa72b496fc4eb2b94a7103baa5ed84917af065fcfc9eab6e3d45c202aafd18150c1e92aff9fe795c6d582ee096158c8f4c3694d106b4ff1cf0b8b7109beda306fb0d058f34e3891648ab72f4e82651e4c9548674e89b0a940c17d33d15a82b97cd33862c7dfbe1f3326b77ec8b08a72d81a628a7205ee05fc50373465139cdbe8b85f1a6fb48cf101b2d740a3f38af31955b9586825c457fb77e78766cb23b9318c6154ae76509e9e684ee6387409e21e48bcafdd253a7eba93b8d6527f939067bcf125df3abf06267b30a28eb56f3ac54f4319650c59f6e0cbef4cd42a5bb6744d68d4abcccfec61e205a7001ec7f0a75383cca9fadc9826af553b035ce12baed1f09e186a50646308aaa05c5bbcf38d77488464d4ab4305bcca93bab9743ebdff24931c8938b74d1b1fa08a31f342679ef82a6ddbf3a8b5310b15893ab87469ba44fd75ae2a3175ee164632008d3e2088329884859afd23dea9d4a0bbe3675ae36f031375637cabf9335af36216916049609266b3e7f24ccb962d0c6d83075edbe8f392ee293c407bb3fca4c61230c65f338ffeff79100e4f32e45f4c48788d938f19d7c9c8a9c0ee0c0ca79fb1b2dcf582fdb9a0d35ebb64507f9ad55148ad08dadfa7febabf42096675150d9d1291e12349945d6b83f1071a42"

    # dec_data = sm4_ins.decrypt_sm4(secret_key, enc_data, mode='CBC', iv=iv)
    dec_data = sm4_ins.decrypt_sm4(secret_key, enc_data, mode='ECB')
    print("sm4解密结果：", dec_data)  # 解密后的数据
