import json

from protos.common_pb2 import RPCReply, RPCRequest, RequestFile, RequestFiles


def RequestFile_P2T(item):
    return {
        'body': item.body,
        'filename': item.filename,
    }


def RequestFile_T2P(item):
    return RequestFile(
        body=item.get('body', b''),
        filename=item['filename'],
    )


def RequestFiles_P2T(item):
    return [RequestFile_P2T(file) for file in item.files]


def RequestFiles_T2P(item):
    return RequestFiles(
        files=[RequestFile_T2P(file) for file in item],
    )


def Request_P2D(item):
    return {
        'key': json.loads(item.key),
        'params': json.loads(item.params),
        'files': {key: RequestFiles_P2T(file) for key, file in dict(item.files).items()}
    }


def Request_D2P(item):
    return RPCRequest(
        key=json.dumps(item.get('key', {})),
        params=json.dumps(item.get('params', {})),
        files={key: RequestFiles_T2P(file) for key, file in item.get('files', {}).items()}
    )


def Replay_P2D(item):
    return {
        'code': item.code,
        'message': item.message,
        'data': json.loads(item.data),
        'type': item.type,
        'file': item.file,
        'text': item.text,
    }


def Replay_D2P(item):
    return RPCReply(
        code=item.get('code', 200),
        message=item.get('message', ''),
        data=json.dumps(item.get('data')),
        type=item['type'],
        file=item.get('file'),
        text=item.get('text', ''),
    )
