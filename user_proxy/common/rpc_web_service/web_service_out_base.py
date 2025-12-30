import logging

from user_proxy.common.rpc_web_service.common import PackResult, WebServiceException


class WebServiceOutBase:
    GROUP_MAPPING = {}

    @classmethod
    def handler(cls, **kwargs):
        key = kwargs.pop('key')
        classname = key['class']
        web_service = cls.GROUP_MAPPING.get(classname)
        if not web_service:
            logging.error("【Prime】don't found web service: %s", classname)
            from user_proxy.common.rpc_web_service.web_service_base import WebServiceBase
            return WebServiceBase.error(f"don't found web service: {classname}", 404)

        func = getattr(web_service, key['method'])
        if not func:
            from user_proxy.common.rpc_web_service.web_service_base import WebServiceBase
            logging.error("【Prime】%s web service don't found method: %s", web_service.__name__, key['method'])
            return WebServiceBase.error(f"{classname} don't found method: {func}", 404)

        params = kwargs.get('params', {})
        files = kwargs.get('files', {})

        try:
            _type, data = func(files=files, **params)
            result = PackResult.run(_type, data)
        except WebServiceException as e:
            result = PackResult.error(e.detail, e.status_code)
        except Exception as e:
            result = PackResult.process_exception(e)
        return result
