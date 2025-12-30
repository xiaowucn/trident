import functools

from protos.common_pb_trans import Request_P2D, Replay_D2P
from user_proxy.common.rpc_web_service.common import PackResult


def check_run(method):
    @functools.wraps(method)
    def wrapper(client, request, context):
        params = Request_P2D(request)
        try:
            res = method(client, params)
        except Exception as e:
            return Replay_D2P(PackResult.process_exception(e))
        return Replay_D2P(res)
    return wrapper
