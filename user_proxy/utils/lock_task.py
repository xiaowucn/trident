# -*-coding:utf-8-*-
import functools
import logging

from user_proxy.db import render_key
from user_proxy.session import RedisDriver


def lock_task(key=None, exp=60):
    def decorator(method):
        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            cache_key = render_key(key or method.__name__)
            lock = RedisDriver().get_lock(cache_key, exp=exp)
            logging.warning('get lock: %s %s', cache_key, lock)
            if not lock:
                return None
            return method(*args, **kwargs)

        return wrapper

    return decorator
