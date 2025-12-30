from user_proxy.common.rpc_web_service.common import USE_RPC, load_web_service
from user_proxy.common.rpc_web_service.web_service_out_base import WebServiceOutBase
from user_proxy.web_services.htsc_service import HTSCWebService
from user_proxy.web_services.proxy_service import ProxyWebService
from user_proxy.web_services.user_service import UserWebService


class WebServiceOut(WebServiceOutBase):
    GROUP_MAPPING = {
        UserWebService.__name__: UserWebService,
        ProxyWebService.__name__: ProxyWebService,
        HTSCWebService.__name__: HTSCWebService,
    }


# 使用rpc再包装函数
if USE_RPC:
    from rpc_client.rpc_client import RPCClient

    for web_cls in WebServiceOut.GROUP_MAPPING.values():
        load_web_service(web_cls, RPCClient)
