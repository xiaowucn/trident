import logging

from user_proxy.config import get_config
from . import Config, zk_invoke
from .util import DubboException


class DubboApi:
    def __init__(self, config_name='htamc'):
        self.config_name = config_name
        self.init_config(config_name)

    @classmethod
    def init_config(cls, config_name):
        if get_config(f'{config_name}.dubbo.enable', False):
            Config.zookeeper_url_list = get_config(f'{config_name}.dubbo.service.zk_host', '').split(',')
            Config.dubbo_connect_timeout = get_config(f'{config_name}.dubbo.service.timeout') or 10
            Config.zookeeper_connect_timeout = get_config(f'{config_name}.dubbo.service.timeout') or 10

    @classmethod
    def request(cls, interface, method, params, version=None):
        _key = f'{interface}.{method}.{version}'

        data = zk_invoke(interface, method, params or {}, version).get('invoke_data')
        if not data or data['code'] != '0':
            logging.error('%s: htsc数据请求失败: %s', _key, str(data))
            raise DubboException(msg=data['message'], data=data)

        results = data['resultData']
        logging.debug('success: %s : %s', _key, str(results))
        return results

    def request_by_service_key(self, key, params=None):
        return self.request(
            get_config(f'{self.config_name}.dubbo.service.{key}.name'),
            get_config(f'{self.config_name}.dubbo.service.{key}.method'),
            params,
            get_config(f'{self.config_name}.dubbo.service.{key}.version'),
        )
