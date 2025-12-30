import hashlib


def md5sum_for_file(file_path, block_size=2 ** 20) -> str:
    md5 = hashlib.md5()
    stream = open(file_path, "rb")
    while True:
        data = stream.read(block_size)
        if not data:
            break
        md5.update(data)
    return md5.hexdigest()


def md5sum(text) -> str:
    text = text.encode('utf8')
    md5 = hashlib.md5()
    md5.update(text)
    return md5.hexdigest()
