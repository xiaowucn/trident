# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements,too-many-branches
import datetime
import functools
import importlib
import json
import logging
import math
import re
import urllib
from decimal import Decimal
from enum import unique, IntEnum
from json import JSONEncoder
from urllib.parse import urljoin
from uuid import UUID

import psycopg2
import sqlalchemy.exc
import tornado.web
from tornado import gen, iostream
from tornado.concurrent import future_set_result_unless_cancelled
from tornado.escape import utf8
from tornado.log import app_log
from utensils.crypto import PackageEncrypt

from user_proxy import config
from user_proxy.common.rpc_web_service.common import create_tmp_ins, ResultType, check_needs, WebServiceException, USE_RPC
from user_proxy.models.user import User
from user_proxy.session import SessionMixin
from user_proxy.utils import authtoken
from user_proxy.utils.authtoken import validate_url, generate_timestamp
from user_proxy.utils.cas import create_url
from user_proxy.web_services import UserWebService

if not USE_RPC:
    from user_proxy.db import db_session


class route(object):  # pylint: disable=invalid-name
    HANDLERS = []

    def __init__(self, router_url, prefix="/api/v1"):
        self.router_url = router_url
        self.prefix = prefix

    def __call__(self, clz):
        url = "{}{}".format(self.prefix, self.router_url)
        self.__class__.HANDLERS.append((url, clz))
        for method in config.get_config('webif.http_secure_map', {}):
            if method.lower() not in clz.__dict__:
                continue
            new_url = '%s/%s' % (url, method.lower())
            newclz = type('%s%s%s' % ('Secure', method.capitalize(), clz.__name__), (clz,), {})
            self.__class__.HANDLERS.append((new_url, newclz))
        return clz

    @classmethod
    def get_handlers(cls):
        handlers = ['proxy', 'user', 'custom', 'casdoor']
        if config.get_config('webif.debug_frontend_upstream'):
            handlers.append("index")
        if config.get_config('webif.debug'):
            handlers.append('debug')
        config_sys = config.get_config('sys')
        if config_sys == 'sse-autodoc':
            handlers.append('sse')
        elif config_sys == 'citics-tg':
            handlers.append('citics')
        elif config_sys == 'gtja_llm':
            handlers.append('gtja')
        elif config_sys == 'gjzq':
            handlers.append('cmfchina')
        else:
            handlers.append(config_sys)
        for handler in handlers:
            handler_module = "user_proxy.handlers.{}".format(handler)
            try:
                importlib.import_module(handler_module)
            except ModuleNotFoundError:
                logging.warning('import handlers module error, %s not found', handler_module)
        return cls.HANDLERS


class TokenAuth(object):
    def __init__(self, config_prefix="webif.auth_common", api=True, url_process_func=None):
        self.api = api
        self.config_prefix = config_prefix

        self.token_auth_on = config.get_config("{}.enable".format(self.config_prefix), False)
        self.app_id = config.get_config("{}.app_id".format(self.config_prefix))
        self.secret = config.get_config("{}.secret_key".format(self.config_prefix))
        self.token_expire = config.get_config("{}.token_expire".format(self.config_prefix)) or 3600
        self.exclude_domain = config.get_config("{}.exclude_domain".format(self.config_prefix), False)
        self.token_single_effective = config.get_config("{}.token_single_effective".format(self.config_prefix), False)
        self.url_process_func = url_process_func

    def auth_check(self, this):
        if self.token_auth_on:
            url = this.request.headers.get('X-Real-FULLURL', None) or this.request.full_url()
            logging.info('auth token check full url: %s', url)
            if self.url_process_func is not None:
                url = self.url_process_func(url)
            logging.info('auth token check after process url: %s', url)
            if self.token_single_effective:
                if this.session.driver.client.get(this.get_argument('_token')):
                    return False
                this.session.driver.client.setex(this.get_argument('_token'), common_token_auth.token_expire, str(generate_timestamp()))
            return authtoken.validate_url(url, self.app_id, self.secret, token_expire=self.token_expire, exclude_domain=self.exclude_domain)
        return True

    def __call__(self, method):
        @functools.wraps(method)
        def wrapper(this, *args, **kwargs):
            if not self.auth_check(this):
                raise tornado.web.HTTPError(403)
            return method(this, *args, **kwargs)

        return wrapper


common_token_auth = TokenAuth()


def permission_auth(needs=None, token=False):
    def decorator(method):
        @functools.wraps(method)
        def wrapper(handler, *args, **kwargs):
            config_sys = config.get_config('sys')
            subpath = config.get_config("webif.redirect_subpath", '')
            base_url = urljoin(handler.origin_host, subpath.lstrip('/'))
            is_mszq_oa_user = (
                config_sys == 'mszq' and handler.current_user and handler.current_user.oa_user and handler.current_user.user_data.get('custom_system') != 'cas'
            )
            if is_mszq_oa_user:
                token_cookie_key = config.get_config('mszq_auth.token_cookie_key')
                mszq_token = handler.get_cookie(token_cookie_key)
                sso_attribute_session_key = config.get_config('mszq_auth.sso_attribute_session_key')
                sso_attribute = handler.get_cookie(sso_attribute_session_key)
                if not mszq_token or not sso_attribute or mszq_token != sso_attribute:
                    return handler.error('need sso login', redirect=urljoin(base_url, 'api/v1/mszq/sso-login'), status_code=HTTPErrorCode.FRONT_REDIRECT.value)

            if token and handler.check_token():
                return method(handler, *args, **kwargs)
            if handler.session.single_logout():
                if config_sys == 'mszq':
                    return handler.error(
                        'need sso logout',
                        redirect=urljoin(base_url, 'api/v1/mszq/sso-logout' if is_mszq_oa_user else 'api/v1/mszq/sso-logout?custom_system=cas'),
                        status_code=HTTPErrorCode.FRONT_REDIRECT.value,
                    )
            if handler.current_user and handler.check_needs(needs):
                return method(handler, *args, **kwargs)
            elif config_sys == 'gffunds':
                handler.clear_all_cookies()
                return handler.error('unauthorized', status_code=401)
            elif handler.request.path == '/api/v1/user/me':
                return handler.error('unauthorized', status_code=401)
            else:
                if config_sys in ['csc', 'zts', 'cjsc', 'htffund']:
                    return handler.redirect(urljoin(base_url, 'api/v1/user/cas-login'))
                elif config_sys in ['cms', 'swsc', 'guosen', 'gtja']:
                    return handler.redirect(urljoin(base_url, f'api/v1/{config_sys}/sso-login'))
                elif config_sys == 'cicc':
                    if config.get_config('sso_auth_use') == 'cicc_auth':
                        return handler.redirect(create_url(urljoin(base_url, 'api/v1/cicc/sso-login'), None, ('target_uri', handler.request.uri)))
                    else:
                        query_token = handler.get_argument('token')
                        return handler.redirect(
                            create_url(urljoin(base_url, 'api/v1/cicc/sso-login-2'), None, ('origin', handler.request.uri), ('token', query_token))
                        )
                elif config_sys == 'htsc':
                    user_id = handler.get_argument('userId')
                    return handler.redirect(create_url(urljoin(base_url, 'api/v1/htsc/sso-login'), None, ('origin', handler.request.uri), ('userId', user_id)))
                elif config_sys == 'ccxi':
                    redirect = handler.get_argument('redirect', None)
                    sys = handler.get_argument('sys')
                    return handler.redirect(create_url(urljoin(base_url, 'api/v1/ccxi/cas-login'), None, ('redirect', redirect), ('sys', sys)))
                elif config_sys == 'dxzq':
                    ticket = handler.get_argument('ticket')
                    return handler.redirect(create_url(urljoin(base_url, 'api/v1/dxzq/sso-login'), None, ('origin', handler.request.uri), ('ticket', ticket)))
                else:
                    if config.get_config('sso_auth_use') == 'casdoor_auth':
                        return handler.redirect(create_url(urljoin(base_url, 'api/v1/casdoor/sso-login'), None, ('target_uri', handler.request.uri)))
            return handler.error('unauthorized', status_code=401)

        return wrapper

    return decorator


class BaseHandler(tornado.web.RequestHandler, SessionMixin):
    def __init__(self, application, request, **kwargs):
        super(BaseHandler, self).__init__(application, request, **kwargs)
        binary_key = config.get_config('webif.binary_key', "key")
        self.package_encrypt = PackageEncrypt(binary_key)
        self.handshake_encrypt = PackageEncrypt('0b168d3bb0828b5f6242cb3a9f144a23')

    @classmethod
    def form_errors_to_str(cls, dct):
        return "{" + ", ".join([key + ": " + "[" + ", ".join(values) + "]" for key, values in dct.items()]) + "}"

    def initialize(self):
        """
        Hook for subclass initialization. Called for each request.
        before __init__
        """
        self.http_secure_map = config.get_config('webif.http_secure_map', {})
        if not self.http_secure_map:
            return
        # 禁用不安全的http方法（put/post）
        if self.request.method in self.http_secure_map:
            raise tornado.web.HTTPError(405)
        if not hasattr(self, 'url') or self.url is None:
            logging.warning('%s has no url attribute, please check your code', self)
            return
        http_method = self.url.split('/')[-1].upper()
        if http_method in self.http_secure_map:
            setattr(self, self.http_secure_map[http_method].lower(), getattr(self, http_method.lower()))

    def options(self):
        self.set_cors_header()
        self.set_status(204)
        self.finish()

    def set_cors_header(self):
        origin = f'{self.request.headers.get("Origin", "").rstrip("/")}'
        systems = config.get_config('unify_auth.auth_config')
        if origin not in [s.get('host') for s in systems.values() if s.get('host')]:
            logging.warning('Untrusted source request detected: %s', origin)
            return None
        # NOTE: Can't be set "*" because a valid request always sending with cookies
        # which will be blocked by CORS policy
        self.set_header("Access-Control-Allow-Origin", origin)
        # Must be set as "true"(case sensitive) to allow CORS with cookies
        self.set_header("Access-Control-Allow-Credentials", "true")
        self.set_header("Access-Control-Allow-Methods", "POST, GET, PUT, DELETE, OPTIONS")
        # Must contain all possible request headers from frontend requests
        possible_headers = ["Host", "User-Agent", "Accept", "Accept-Language", "Accept-Encoding", "Origin", "X-Csrftoken", "Referer", "Connection"]
        allow_headers = set(list(self.request.headers) + possible_headers)
        self.set_header("Access-Control-Allow-Headers", ", ".join(allow_headers))
        self.set_header("Vary", "Accept-Encoding, Origin")

    def data_received(self, chunk):
        pass

    def prepare(self):
        if self.request.method.lower() in ('post', 'put'):
            route_list = config.get_config('webif.encrypted_request_routes', [])
            for route_ext in route_list:
                if 'all' in route_list or re.search(rf'^/api/v\d+{route_ext}$', self.request.path):
                    logging.debug('Decrypt request body for route: %s', self.request.path)
                    try:
                        self.request.body = self.request_encrypt.decrypt(self.request.body)
                    except ValueError:
                        self.error('Cryptographic handshake failed')
                        self.finish()
                    break

    def check_xsrf_cookie(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS") or not config.get_config('webif.xsrf_cookies', False):
            return None
        for route_ext in config.get_config('webif.trust_routes', []):
            if re.search(rf'^/api/v\d+{route_ext}$', self.request.path):
                logging.debug('Skip xsrf check: %s', self.request.path)
                return None
        url = self.request.full_url()
        query = urllib.parse.urlparse(url).query
        params = urllib.parse.parse_qs(query) if query else {}
        if all([v for k, v in params.items() if k in ('_token', '_timestamp')] or [None]):
            logging.debug('Skip xsrf check: %s', self.request.path)
            return None
        try:
            super(BaseHandler, self).check_xsrf_cookie()
        except tornado.web.HTTPError as exp:
            self.error(str(exp), exp.status_code)
            self.finish()
        return None

    @property
    def origin_host(self):
        url_host = self.get_argument('host', None)
        if url_host:
            return url_host
        scheme = self.request.headers.get('X-Scheme') or 'http'
        origin_host = self.request.headers.get('X-Real-Host') or self.request.headers.get('Host') or self.request.host
        origin_host = scheme + '://' + origin_host
        return origin_host

    def gen_redirect_url(self, url, base_url='', subpath=''):
        if url and url.startswith(('http', 'https')):
            return url
        base_url = base_url or self.origin_host
        subpath = subpath or config.get_config('webif.redirect_subpath', '')
        prefix = urljoin(base_url, subpath.lstrip('/'))
        prefix = prefix.rstrip('/')
        if not url:
            url = prefix
        elif url.startswith('/'):
            url = prefix + url
        else:
            url = prefix + '/' + url
        return url

    def redirect(self, url, permanent=False, status=None):
        """Sends a redirect to the given (optionally relative) URL.

        If the ``status`` argument is specified, that value is used as the
        HTTP status code; otherwise either 301 (permanent) or 302
        (temporary) is chosen based on the ``permanent`` argument.
        The default is 302 (temporary).
        """
        if self._headers_written:
            raise Exception("Cannot redirect after headers have been written")
        if status is None:
            status = 301 if permanent else 302
        else:
            assert isinstance(status, int) and 300 <= status <= 399
        url = self.gen_redirect_url(url)
        self.set_status(status)
        self.set_header("Location", utf8(url))
        self.finish()

    @gen.coroutine
    def _execute(self, transforms, *args, **kwargs):  # pylint:disable=invalid-overridden-method
        self._transforms = transforms
        try:
            if self.request.method not in self.SUPPORTED_METHODS:
                raise tornado.web.HTTPError(405)
            self.path_args = [self.decode_argument(arg) for arg in args]
            self.path_kwargs = dict((k, self.decode_argument(v, name=k)) for (k, v) in kwargs.items())
            # If XSRF cookies are turned on, reject form submissions without
            # the proper cookie
            if self.request.method not in ("GET", "HEAD", "OPTIONS") and self.application.settings.get("xsrf_cookies"):
                self.check_xsrf_cookie()

            result = self.prepare()  # pylint: disable=assignment-from-no-return
            if result is not None:
                result = yield result
            if self._prepared_future is not None:
                # Tell the Application we've finished with prepare()
                # and are ready for the body to arrive.
                future_set_result_unless_cancelled(self._prepared_future, None)
            if self._finished:
                return

            if tornado.web._has_stream_request_body(self.__class__):  # pylint: disable=protected-access
                # In streaming mode request.body is a Future that signals
                # the body has been completely received.  The Future has no
                # result; the data has been passed to self.data_received
                # instead.
                try:
                    yield self.request.body
                except iostream.StreamClosedError:
                    return

            method = getattr(self, self.request.method.lower())
            result = method(*self.path_args, **self.path_kwargs)
            if result is not None:
                result = yield result
            if self._auto_finish and not self._finished:
                self.finish()
        except WebServiceException as e:
            self.error(e.detail, e.status_code)
            self.finish()
        except Exception as e:
            try:
                self._handle_request_exception(e)
            except Exception:
                app_log.error("Exception in exception handler", exc_info=True)
            finally:
                # Unset result to avoid circular references
                result = None
            if self._prepared_future is not None and not self._prepared_future.done():
                # In case we failed before setting _prepared_future, do it
                # now (to unblock the HTTP server).  Note that this is not
                # in a finally block to avoid GC issues prior to Python 3.4.
                self._prepared_future.set_result(None)

    def log_exception(self, typ, value, tb):
        if not USE_RPC and isinstance(value, (psycopg2.DatabaseError, sqlalchemy.exc.SQLAlchemyError)):
            db_session.rollback()  # pylint:disable=possibly-used-before-assignment
        super(BaseHandler, self).log_exception(typ, value, tb)

    def get_json_body(self, binary=None):
        body = self.request.body
        if not body:
            return None
        binary = config.get_config('webif.binary_json', False) if binary is None else binary
        if binary:
            body = self.package_encrypt.decrypt_json(body)
            return body
        return tornado.escape.json_decode(body)

    def check_token(self):
        return validate_url(self.request.full_url())

    def check_needs(self, needs):
        return check_needs(self.current_user, needs)

    def get_current_user(self):
        uid_in_cookie = self.session['proxy_user_id']

        if uid_in_cookie is None:
            return None

        user = create_tmp_ins(User, UserWebService.get_current_user(user_id=int(uid_in_cookie)))

        if not user:
            return None

        return user

    def check_permission(self):
        if not self.current_user:
            return False
        return True

    def hand_out_data(self, data):
        """
        分类返回业务service层返回的数据到前端
        :param data:
        :return:
        """
        _type, res = data
        if _type in [ResultType.JSON.value, ResultType.TEXT.value]:
            return self.data(res)
        elif _type == ResultType.FILE.value:
            extra_data, file_content = data
            for key, val in extra_data.get('headers', {}).items():
                self.set_header(key, val)

            block_len = 1024
            for idx in range(math.ceil(len(file_content) / block_len)):
                block = file_content[idx * block_len : (idx + 1) * block_len]
                if block:
                    self.write(block)
                else:
                    break
            self.finish()
        elif _type == ResultType.REDIRECT.value:
            url, code = res
            self.redirect(url, status=code)
        elif _type == ResultType.REDIRECT_PLUS.value:
            data, code = res
            self.redirect(data['redirect_url'], status=code)
        elif _type == ResultType.HTML.value:
            data, code = res
            self.set_header("Content-Type", 'text/html')
            self.set_status(code)
            self.write(data)
        else:
            logging.error('web client result error, not found type: %s', str(data))

    def get_pagination_args(self):
        page = max(int(self.get_argument("page", "1")), 1)
        size = int(self.get_argument("size", "20"))
        return page, size

    def is_admin(self):
        return self.current_user and self.current_user.is_admin

    def send_json(self, data, binary=False, handshake=False, caching_time=0):
        if self._finished:
            return
        if caching_time:
            self.set_header("Cache-Control", "max-age=%s" % str(caching_time))
        else:
            self.set_header("Cache-Control", "no-store, no-cache")
        if handshake:
            message = self.handshake_encrypt.encrypt_json(data)
            self.write(message)
        elif binary:
            message = self.package_encrypt.encrypt_json(data)
            self.write(message)
        else:
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps(data, ensure_ascii=False, cls=CustomJSONEncoder))

    def data(self, data, binary=False, handshake=False, caching_time=0):
        self.send_json({"status": "ok", "data": data}, binary=binary, handshake=handshake, caching_time=caching_time)

    def error(self, message, status_code=400, binary=False, handshake=False, **kwargs):
        self.set_status(status_code)
        body = {"status": "error", "message": message}
        if kwargs:
            body.update(kwargs)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.send_json(body, binary=binary, handshake=handshake)

    def flush(self, include_footers=False):
        self.session_commit()
        super(BaseHandler, self).flush(include_footers)

    def on_finish(self):
        if not USE_RPC:
            db_session.commit()


class LoginLimitManager(object):
    PREFIX = 'login_limit'
    PERIOD = config.get_config('webif.session.check_wrong_password_times.limit_seconds', 30 * 60)
    EXPIRED_PERIOD = config.get_config('webif.session.check_wrong_password_times.lock_expired_seconds', 1800)
    TIMES = config.get_config('webif.session.check_wrong_password_times.login_failed_numbers', 5)

    def __init__(self, redis, ip_address, username):
        self.redis = redis
        self.key = ':'.join((self.PREFIX, ip_address, username))

    def clear(self):
        self.redis.delete(self.key)

    def get_times(self):
        return self.redis.get(self.key)

    def incr(self):
        times = self.redis.get(self.key)
        if not times:
            self.redis.set(self.key, 0, ex=self.PERIOD)
        times = int(self.redis.incr(self.key))
        if times == self.TIMES:
            self.refresh()

    def refresh(self):
        self.redis.expire(self.key, self.EXPIRED_PERIOD)


def clear_captcha(handler):
    handler.session['captcha'] = ''


@unique
class HTTPErrorCode(IntEnum):
    SINGLE_SIGN_LOGOUT = 402  # 当同一账号在其他地方登录时已登录的账号应退出会话
    PASSWORD_EXPIRED = 418  # 密码过期，需重新设置密码
    FRONT_REDIRECT = 306  # 返回redirect数据，前端直接跳转


class CustomJSONEncoder(JSONEncoder):
    def default(self, obj):  # pylint: disable=arguments-renamed
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, datetime.datetime):
            return obj.timestamp()
        elif isinstance(obj, Decimal):
            return float(obj) if not obj.is_nan() else 0.0
        elif isinstance(obj, datetime.date):
            return obj.strftime("%Y-%m-%d")
        # elif isinstance(obj, numpy.int64):
        #     return int(obj)
        return JSONEncoder.default(self, obj)
