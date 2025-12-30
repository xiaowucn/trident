import functools
import json
import logging
from datetime import datetime

import grpc

from protos.common_pb_trans import Replay_P2D, Request_D2P
from user_proxy import config

from grpc._cython.cygrpc import CompressionAlgorithm, CompressionLevel


def load_stub(handler):
    @functools.wraps(handler)
    def wrapper(client, classname, method, *args, **kwargs):
        if client.USE_RPC and not client.SERVICE_STUB:
            client.create_stub()
        logging.info('%s call rpc start: %s.%s', datetime.now(), classname, method)
        try:
            return handler(client, classname, method, *args, **kwargs)
        finally:
            logging.info('%s call rpc end: %s.%s', datetime.now(), classname, method)
    return wrapper


class ClientBase:
    USE_RPC = config.get_config('rpc.web.enable', False)
    TARGET = config.get_config('rpc.web.target')
    MAX_RECEIVE_MESSAGE_LENGTH = config.get_config('rpc.web.max_receive_message_length', 104857600)
    STUB_CLASS = None
    SERVICE_STUB = None
    CHANNEL = None

    @classmethod
    def close_connection(cls):
        try:
            cls.CHANNEL.close()
            cls.SERVICE_STUB = None
        except Exception as e:  # pylint:disable=broad-except
            logging.error("close rpc channel error: %s", e)

    @classmethod
    def create_stub(cls):
        if not cls.USE_RPC or cls.SERVICE_STUB:
            return
        options = [
            ('grpc.max_receive_message_length', cls.MAX_RECEIVE_MESSAGE_LENGTH),
            ('grpc.default_compression_algorithm', CompressionAlgorithm.gzip),
            ('grpc.grpc.default_compression_level', CompressionLevel.high),

        ]

        if config.get_config('rpc.web.keepalive.enable'):
            options.extend([
                ('grpc.keepalive_time_ms', config.get_config('rpc.web.keepalive.time', 7200000)),
                ('grpc.keepalive_timeout_ms', config.get_config('rpc.web.keepalive.timeout', 10000)),
                ('grpc.keepalive_permit_without_calls', config.get_config('rpc.web.keepalive.permit_without_calls', 0)),
                ('grpc.http2.max_pings_without_data', config.get_config('rpc.web.keepalive.max_pings_without_data', 2)),
            ])

        # NOTE: 启动重试模式， 默认在v1.40.0后自动启用
        enable_retries = int(config.get_config('rpc.web.enable_retries') or 0)
        if enable_retries:
            # 第一次重试间隔是 random(0, initialBackoff)
            # 第 n 次的重试间隔为 random(0, min( initialBackoff*backoffMultiplier**(n-1) , maxBackoff))
            service_config_json = json.dumps({
                "methodConfig": [{
                    "name": [{}],
                    # "timeout": '10s',
                    "retryPolicy": {
                        "maxAttempts": 4,
                        "initialBackoff": "0.2s",
                        "maxBackoff": "2s",
                        "backoffMultiplier": 2,
                        "retryableStatusCodes": ["UNAVAILABLE", 'DEADLINE_EXCEEDED'],
                    },
                }],
                "retryThrottling": {
                    "maxTokens": config.get_config('rpc.web.retryThrottling.maxTokens', 10),
                    "tokenRatio": config.get_config('rpc.web.retryThrottling.tokenRatio', 0.1),
                }
            })

            options.append(("grpc.enable_retries", enable_retries))
            # 重试的一些参数配置
            options.append(("grpc.service_config", service_config_json))

        cls.CHANNEL = grpc.insecure_channel(cls.TARGET, options=options)
        cls.SERVICE_STUB = cls.STUB_CLASS(cls.CHANNEL)

    @classmethod
    @load_stub
    def handler(cls, classname, method, files=None, **params):
        # 组装分发业务函数的参数
        params = params or {}
        files = files or {}

        data = {'key': {'class': classname, 'method': method},
                'params': params,
                'files': files
                }

        return Replay_P2D(cls.SERVICE_STUB.Handler(Request_D2P(data), timeout=config.get_config('rpc.web.timeout', 20)))
