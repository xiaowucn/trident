# -*-coding:utf-8-*-
import base64
import json

from gmssl import sm2

from user_proxy.utils.authtoken import generate_timestamp


class CMBSM2SignWithSM3:
    def __init__(self, private_key, public_key):
        if private_key:
            private_key = base64.b64decode(private_key.encode()).hex()
        if public_key:
            public_key = base64.b64decode(public_key.encode()).hex()
            public_key = public_key[2:] if (public_key.startswith("04") and len(public_key) == 130) else public_key
        self.algorithms = sm2.CryptSM2(private_key, public_key)

    def sm2_verify_with_sm3_jwt_token(self, jwt_token):
        jwt_parts = jwt_token.split('.')
        msg = jwt_parts[0] + '.' + jwt_parts[1]
        return self.sm2_verify_with_sm3(jwt_parts[2], msg)

    def sm2_verify_with_sm3(self, signature, msg):
        signature_b64 = base64.urlsafe_b64decode((signature + '====').encode()).hex()
        return self.algorithms.verify_with_sm3(signature_b64, msg.encode())

    @staticmethod
    def decode_jwt_token(jwt_token):
        payload = jwt_token.split(".")[1]
        padding = "=" * (4 - (len(payload) % 4))
        return json.loads(base64.urlsafe_b64decode(payload + padding).decode())

    def verify_token_expire(self, jwt_token):
        data = self.decode_jwt_token(jwt_token)
        if data['exp'] <= generate_timestamp():
            return False
        return True

    def verify_audience(self, jwt_token, audience):
        if not audience:
            return True
        data = self.decode_jwt_token(jwt_token)
        aud = data['aud']
        if isinstance(aud, str):
            aud = json.loads(aud)
        if aud['id'] != audience:
            return False
        return True

    def verify(self, jwt_token, audience=None):
        if not self.verify_audience(jwt_token, audience):
            return False, '非本应用token'
        if not self.verify_token_expire(jwt_token):
            return False, 'token已过期'
        if not self.sm2_verify_with_sm3_jwt_token(jwt_token):
            return False, '签名验证失败'
        return True, '认证成功'

    def sm2_sign_with_sm3(self, msg):
        new_sign = self.algorithms.sign_with_sm3(msg.encode())
        return base64.urlsafe_b64encode(bytes.fromhex(new_sign)).decode()


if __name__ == "__main__":
    client_id = 'a806eec13b3f4dc0ab6fdb98fda7b2fc'
    _jwt_token = 'eyJraWQiOiJTTTNXaXRoU00yIiwidHlwIjoiSldUIiwiYWxnIjoiU00zV2l0aFNNMiJ9.eyJqb2luZWRFbnRlcnByaXNlSWRzIjoidWF0ZjA0YTY3MDU4ODJhYzAxNzA1ODhmMGQ4NzAwMGMiLCJwYXRoTmFtZSI6IuaLm-WVhumTtuihjC_mgLvooYwv5L-h5oGv5oqA5pyv6YOoL-aVsOaNrui1hOS6p-S4juW5s-WPsOeglOWPkeS4reW_gy_kurrlt6Xmmbrog73lrp7pqozlrqQv6K6k55-l6K6h566X5LqM5a6kKOaIkOmDvSkiLCJzdWIiOiJCNUEzNkExRjM4OEQ5MEU0RkJDRkVCRTdCOEMyOUM2MCIsIm9wZW5JZCI6IkI1QTM2QTFGMzg4RDkwRTRGQkNGRUJFN0I4QzI5QzYwIiwib3JpZ2luUGF0aElkIjoiMTAwMDAxLzEwMDAwMy85OTAwMDEvOTkxMTY3Lzk5MDc2Ni85OTE2MTgiLCJkZWZhdWx0RW50ZXJwcmlzZUlkIjoidWF0ZjA0YTY3MDU4ODJhYzAxNzA1ODhmMGQ4NzAwMGMiLCJpc3MiOiJvYS1hdXRoLnBhYXMuY21iY2hpbmEuY29tIiwieXN0SWQiOiIyNzM2OTUiLCJwYXRoSWQiOiIyYzllYmZiMTcxYzNmYzdiMDE3MWM0ZGNmYjljNGFiMi8yYzllYmZiMTcxYzNmYzdiMDE3MWM0ZGNmYmZlNGFiNS8yYzllYmZiMTcxYzNmYzdiMDE3MWM0YzZjYjRlMTA2Ni8yYzllYmZiMTcxYzNmYzdiMDE3MWM0YzZjZmU2MTA3Yi8yYzllYmZiMTcxYzNmYzdiMDE3MWM0Yzc3ZjlhMTQxNS8yYzlmZDVhZTc2ZjY1OWUzMDE3NzIyYWJjNWMxNWI4MiIsIm9yZ0lkIjoiMmM5ZmQ1YWU3NmY2NTllMzAxNzcyMmFiYzVjMTViODIiLCJleHAiOjE3MjE2Mzg5NjcsImlhdCI6MTcyMTYyODE2NywiZW50ZXJwcmlzZU5hbWUiOiLmi5vllYbpk7booYwiLCJzYXBJZCI6IjgwMjczNjk1Iiwib3JnTmFtZSI6IuiupOefpeiuoeeul-S6jOWupCjmiJDpg70pIiwib3JpZ2luT3JnSWQiOiI5OTE2MTgiLCJwYXNzZWRBdXRoVHlwZXMiOiJ7XCJ2ZXJpZnlDb2RlXCI6MTcyMTYxNzI4NjgyOX0iLCJuZXRFbnYiOjAsImVtcGxveWVlSWQiOiI4MDI3MzY5NSIsInVzZXJOYW1lIjoi5pyx55Ge5bOwIiwiYXVkIjoie1wiaWRcIjpcImE4MDZlZWMxM2IzZjRkYzBhYjZmZGI5OGZkYTdiMmZjXCIsXCJuYW1lXCI6XCJMTE1fc3RcIixcIm51bWJlclwiOlwiQUEwMS4wMVwiLFwicHVibGljS2V5XCI6XCJCUFQrVEluUmMzaTBBazNRWDYrdU53WmUrTWl6Y1JGSzJLRS9zbjMvUlpyMEM2TDBwbGlVU1haenlzZC9kOHNYdWgvMHdtT1VXekdoZ3VVOUhRTDF1VGM9XCJ9IiwicGxhdGZvcm1Vc2VyVHlwZSI6IjEiLCJjbGllbnRJcCI6Ijk5LjE3LjIwOS40MCIsImVudGVycHJpc2VJZCI6InVhdGYwNGE2NzA1ODgyYWMwMTcwNTg4ZjBkODcwMDBjIiwidXNlclR5cGUiOiIyIn0.j3gqoPuT35G9pxSvG0YKAfITe0gaF3pu7kHhwBL9IkKAxpNcKHG7iFkokkNodFgqTTjcBI-jEus1nduImZ_Cpw'
    # 校验token
    # service_public_key = 'BE5Ov9833ssmHdy5/ixTRJQ4JJH+bMb92LVUmFBs3RGxZXmiaU8AqOV++OaO2DqJrSOpdZZqMM+8CLUCv3b4cog='
    # cmb_decrypt_signer = CMBSM2SignWithSM3('', service_public_key)
    # cmb_decrypt_signer.verify(_jwt_token, client_id)

    # 生成测试用户jwt_token
    user_data = CMBSM2SignWithSM3.decode_jwt_token(_jwt_token)
    user_data.update({"ystId": "80354", "employeeId": "80354960", "userName": "cmb测试普通用户1", "role_id": 5, "exp": generate_timestamp() + 30 * 60 * 60 * 24})
    client_private_key = "Ev6dYQrht/YP6CFNb/rEbEK97uQRTI31Lrx5kO7OkqM="
    client_public_key = "BOKvpipe6aM7xn9sh7V3Y3+lYCl20cEwYiihj3d/hkORpyvTC90pMtVfScR0oSpLU2PqctSOvjsFzVpF0JePtGE="
    cmb_encrypt_signer = CMBSM2SignWithSM3(client_private_key, client_public_key)
    header_payload = 'eyJraWQiOiJTTTNXaXRoU00yIiwidHlwIjoiSldUIiwiYWxnIjoiU00zV2l0aFNNMiJ9'
    json_payload = base64.urlsafe_b64encode(json.dumps(user_data, separators=(",", ":")).encode("utf-8")).decode()
    sign = cmb_encrypt_signer.sm2_sign_with_sm3(f'{header_payload}.{json_payload}')
    token = f'{header_payload}.{json_payload}.{sign}'
    flag, message = cmb_encrypt_signer.verify(token, client_id)
    print(token)
