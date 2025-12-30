#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Basic run script"""
import logging

import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.autoreload
import wtforms_json
from tornado.options import options

from user_proxy import config
from user_proxy.handlers.base import route

wtforms_json.init()


class TornadoApplication(tornado.web.Application):

    def __init__(self):
        logging.info("start user_proxy")
        handlers = route.get_handlers()
        logging.info("handler list:")
        for url, clz in handlers:
            setattr(clz, 'url', url)
            logging.info(url)

        settings = {
            'compiled_template_cache': False,
            'template_path': config.path('user_proxy/templates'),
            'serve_traceback': config.get_config("webif.debug", True),
            'xsrf_cookies': config.get_config('webif.xsrf_cookies', False),
            'xsrf_cookie_kwargs': dict(httponly=True),
            "cookie_secret": "cKYrawHcxeggNAmw3dzHzmPfy",
        }
        tornado.web.Application.__init__(self, handlers, debug=config.get_config("webif.debug", True), **settings)


def setup_options():
    del options._options["logging"]  # reset logging level, pylint: disable=protected-access
    options.define("logging", default=config.get_config("logging.level", default="debug"), help="logging level")
    options.define("port", default=config.get_config("webif.http_port"), help="run on the given port ", type=int)
    tornado.options.parse_command_line()


def serve():
    setup_options()
    try:
        app = TornadoApplication()
        server = tornado.httpserver.HTTPServer(app, max_buffer_size=config.get_config('webif.max_buffer_size', 1024**3))
        server.bind(options.port, reuse_port=True)
        server.start()
        logging.info("Server started... http://localhost:%s\n", options.port)
        tornado.ioloop.IOLoop.current().start()
    except Exception as e:  # pylint: disable=broad-except
        logging.error('catch exception: %s', e)
        raise


if __name__ == '__main__':
    serve()
