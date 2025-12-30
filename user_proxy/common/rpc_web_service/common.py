import functools
import logging

from enum import Enum
from http.client import HTTPException

import grpc
from grpc.aio import AioRpcError

from user_proxy import config
from user_proxy.handlers.message import USER_NOT_EXISTS
from user_proxy.models.user import User


class ResultType(Enum):
    JSON = 'JSON'
    FILE = 'FILE'
    REDIRECT = 'REDIRECT'
    REDIRECT_PLUS = 'REDIRECT_PLUS'
    TEXT = 'TEXT'
    HTML = 'HTML'


class WebServiceException(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"{class_name}(status_code={self.status_code!r}, detail={self.detail!r})"


USE_RPC = config.get_config('rpc.web.enable', False)


def create_tmp_ins(model_class, result):
    if result[0] == ResultType.JSON.value:
        return model_class.create_tmp_ins(result[1])
    return None


class WebSeviceMethodClass:
    MANUAL_RETRY = config.get_config('rpc.web.manual_retry')

    def __init__(self, service_class, method, client_class):
        self.service_class = service_class
        self.client_class = client_class
        self._origin_method_name = self.gen_origin_method_name(method.__func__.__name__)

    def call(self, retry_rpc_error=False, **kwargs):
        try:
            result = self.client_class.handler(classname=self.service_class.__name__,
                                               method=self._origin_method_name, **kwargs)
            # 将rpc结构解析到与业务层一样的格式，错误直接拿异常抛出
            return self.parse_rpc_result(result)
        except WebServiceException as e:
            raise e
        except grpc.RpcError as e:
            if retry_rpc_error and e.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                raise e
            logging.error(e)
            raise WebServiceException(status_code=500, detail='业务服务异常，请稍后重试！')
        except Exception as e:
            logging.error(e)
            raise WebServiceException(status_code=500, detail=str(e))

    def __call__(self, **kwargs):
        try:
            return self.call(retry_rpc_error=self.MANUAL_RETRY, **kwargs)
        except grpc.RpcError as e:
            logging.error('rpc error -> manual retry: %s', e)
            self.client_class.close_connection()
            return self.call(retry_rpc_error=False, **kwargs)

    def origin_method_name(self):
        return self._origin_method_name

    @classmethod
    def parse_rpc_result(cls, res):
        """
        分类返回rpc返回的数据
        :param res:
        :return:
        """
        if res['type'] == ResultType.JSON.value:
            if res['code'] == 200:
                return ResultType.JSON.value, res['data']
            else:
                raise WebServiceException(status_code=res['code'], detail=res['message'] or res['data'])
        if res['type'] == ResultType.TEXT.value:
            return ResultType.TEXT.value, res['text']
        elif res['type'] == ResultType.FILE.value:
            return ResultType.FILE.value, (res['data'], res['file'])
        elif res['type'] == ResultType.REDIRECT.value:
            return ResultType.REDIRECT.value, (res['data']['redirect_url'], res['code'])
        elif res['type'] == ResultType.REDIRECT_PLUS.value:
            return ResultType.REDIRECT_PLUS.value, (res['data'], res['code'])
        elif res['type'] == ResultType.HTML.value:
            return ResultType.HTML.value, (res['text'], res['code'])
        else:
            raise WebServiceException(400, f'web client result error, not found type: {str(res)}')

    @classmethod
    def gen_origin_method_name(cls, name):
        return f"___origin_{name}"


def load_web_service(web_cls, client_class):
    # 使用rpc再包装函数
    if not USE_RPC:
        return
    attrs = dict(web_cls.__dict__)
    for name, method in attrs.items():
        if name.startswith('_'):
            continue
        if not isinstance(method, classmethod):
            continue
        new_method = WebSeviceMethodClass(web_cls, method, client_class)
        # 保存原始方法
        setattr(web_cls, new_method.origin_method_name(), method)
        # 替换原始方法
        setattr(web_cls, name, new_method)


class PackResult:
    @classmethod
    def run(cls, _type, data):
        if _type == ResultType.JSON.value:
            return PackResult.data(data)
        elif _type == ResultType.TEXT.value:
            return PackResult.text(data)
        elif _type == ResultType.REDIRECT.value:
            return PackResult.redirect(data)
        elif _type == ResultType.REDIRECT_PLUS.value:
            return PackResult.redirect_plus(data)
        elif _type == ResultType.FILE.value:
            return PackResult.response_file(data)
        elif _type == ResultType.HTML.value:
            return PackResult.template(data)
        else:
            logging.error('PackResult ERROR: type=%s', _type)

    @classmethod
    def template(cls, res):
        data, status_code = res
        return {
            "code": status_code,
            "message": '',
            "text": data,
            "data": {},
            "file": b'',
            'type': ResultType.HTML.value,
        }

    @classmethod
    def response_file(cls, res):
        data, content = res
        return {
            "code": 200,
            "message": '',
            "text": "",
            "data": data,
            "file": content,
            'type': ResultType.FILE.value,
        }

    @classmethod
    def redirect(cls, res):
        re_url, status_code = res
        return {"code": status_code,
                "data": {'redirect_url': re_url},
                "message": '',
                "text": "",
                'type': ResultType.REDIRECT.value,
                'file': b''
                }

    @classmethod
    def redirect_plus(cls, res):
        data, status_code = res
        return {"code": status_code,
                "data": data,
                "message": '',
                "text": "",
                'type': ResultType.REDIRECT_PLUS.value,
                'file': b''
                }

    @classmethod
    def data(cls, data, status_code=200):
        return {"code": status_code,
                "data": data,
                "text": "",
                "message": '',
                'type': ResultType.JSON.value,
                'file': b''
                }

    @classmethod
    def text(cls, text, status_code=200):
        return {"code": status_code,
                "text": text,
                "data": {},
                "message": '',
                'type': ResultType.TEXT.value,
                'file': b''
                }

    @classmethod
    def error(cls, message, status_code=400):
        msg = message
        data = {}
        if isinstance(message, (dict, list)):
            data = message
            msg = ''
        return {"code": status_code,
                "message": msg,
                "text": "",
                "data": data,
                'type': ResultType.JSON.value,
                'file': b''
                }

    @classmethod
    def process_exception(cls, error):
        ret = cls.error('Unknown error!')
        logging.exception(error)
        logging.error('WEB_RPC: %s', str(error))
        if error:
            if isinstance(error, str):
                ret['message'] = error
            elif isinstance(error, grpc.RpcError):
                ret['message'] = error.details()
            elif isinstance(error, HTTPException):
                ret = PackResult.error(error.detail, error.status_code)
            else:
                ret['message'] = str(error)
        return ret


def check_user(method):
    @functools.wraps(method)
    def wrapper(servicer, **kwargs):
        current_user = None
        if kwargs.get('current_user_id'):
            current_user = User.get_by_id(kwargs["current_user_id"])
        if not current_user:
            return servicer.error(USER_NOT_EXISTS, status_code=401)
        return method(servicer, current_user, **kwargs)

    return wrapper


def check_needs(user, needs):
    if not needs:
        return True
    if not user or not user.permissions:
        return False
    return all([True if need in user.permissions else False for need in needs])
