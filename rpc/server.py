import time
from concurrent import futures

import grpc
from grpc._cython.cygrpc import CompressionAlgorithm, CompressionLevel

from protos import trident_pb2_grpc
from rpc.common import check_run
from user_proxy import config
from user_proxy.web_services import WebServiceOut


class MicroService(trident_pb2_grpc.MicroServiceServicer):
    @check_run
    def Handler(self, params):
        return WebServiceOut.handler(**params)


def serve():
    options = [
        ('grpc.max_receive_message_length', config.get_config('rpc.web.max_receive_message_length', 104857600)),
        ('grpc.default_compression_algorithm', CompressionAlgorithm.gzip),
        ('grpc.grpc.default_compression_level', CompressionLevel.high),
    ]

    if config.get_config('rpc.web.keepalive.enable'):
        options.extend([
            ('grpc.keepalive_time_ms', config.get_config('rpc.web.keepalive.time', 7200000)),
            ('grpc.keepalive_timeout_ms', config.get_config('rpc.web.keepalive.timeout', 20000)),
            ('grpc.keepalive_permit_without_calls', config.get_config('rpc.web.keepalive.permit_without_calls', 0)),
            ('grpc.http2.max_pings_without_data', config.get_config('rpc.web.keepalive.max_pings_without_data', 2)),
            ('grpc.http2.min_ping_interval_without_data_ms', config.get_config('rpc.web.keepalive.without_data', 300000)),
            ('grpc.http2.max_ping_strikes', config.get_config('rpc.web.keepalive.strikes', 2)),
        ])

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1), options=options)

    trident_pb2_grpc.add_MicroServiceServicer_to_server(MicroService(), server)

    port = config.get_config('rpc.web.port', 50060)
    server.add_insecure_port('[::]:{}'.format(port))
    server.start()

    return server


if __name__ == "__main__":
    print("starting server...")
    _ = serve()
    print("server started.")
    while True:
        time.sleep(100000)
