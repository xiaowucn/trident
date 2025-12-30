# -*- coding:utf-8 -*-
# pylint: disable=invalid-overridden-method, unnecessary-comprehension
from builtins import str

import nest_asyncio
from tornado import httpclient
from tornado.httpclient import HTTPRequest

from user_proxy.config import get_config
from user_proxy.handlers.base import BaseHandler, route

nest_asyncio.apply()


@route(r'/', prefix="")
class IndexPageHandler(BaseHandler):
    async def get(self):
        await chain(self, '/')


async def chain(handler, url=None):
    backend = get_config('webif.debug_frontend_upstream')

    if not url:
        backend_url = '{}{}'.format(backend, handler.request.uri)
    else:
        backend_url = '{}{}'.format(backend, url)
    http_client = httpclient.AsyncHTTPClient()
    http_request = HTTPRequest(backend_url, headers={k: v for k, v in list(handler.request.headers.items())})
    try:
        response = await http_client.fetch(http_request)
        handler.set_status(response.code)
        handler.clear_header('Content-Type')
        handler.add_header('Content-Type', response.headers['Content-Type'])
        handler.write(response.body)
        handler.finish()
    except Exception as e:
        handler.error(str(e))
    finally:
        http_client.close()


@route(r'/static/.*', prefix="")
class StaticHandler(BaseHandler):
    async def get(self):
        await chain(self)
