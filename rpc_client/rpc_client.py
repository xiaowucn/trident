from protos.trident_pb2_grpc import MicroServiceStub
from rpc_client.client_base import ClientBase


class RPCClient(ClientBase):
    STUB_CLASS = MicroServiceStub
