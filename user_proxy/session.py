# coding:utf-8
import hashlib
import logging
import os
import pickle
from uuid import uuid4
from hashlib import sha256

import redis
import rediscluster
from redis.sentinel import Sentinel

from user_proxy import config
from user_proxy.config import project_root
from user_proxy.db import KEY_PREFIX, render_key
from user_proxy.utils.authtoken import generate_timestamp


class RedisDriver(object):
    EXPIRE_SECONDS = config.get_config("webif.session.expire_seconds", 24 * 60 * 60)
    ONLINE_LIMIT = config.get_config("webif.session.online_limit", 10)
    SETTINGS = {
        "host": config.get_config("webif.session.host"),
        "port": config.get_config("webif.session.port"),
        "password": config.get_config("webif.session.password"),
        "db": config.get_config("webif.session.db", 1),
        "decode_responses": True,
    }
    _connection_pool = None
    session_prefix = KEY_PREFIX or config.get_config('webif.session.prefix', 'trident')
    _hgetall_script = None
    _hmset_script = None
    _client = None

    @classmethod
    def init_connection_pool(cls):
        if cls._connection_pool is None:
            if not cls.SETTINGS.get('host'):
                return None
            cls._connection_pool = redis.ConnectionPool(**cls.SETTINGS)
        return cls._connection_pool

    @classmethod
    def init_cluster_connection_pool(cls):
        if cls._connection_pool is None:
            hosts_list = config.get_config("webif.session.cluster.hosts")
            password = config.get_config("webif.session.cluster.password")
            startup_nodes = [{"host": item.split(":")[0], "port": item.split(":")[1]} for item in hosts_list]
            cls._connection_pool = rediscluster.ClusterConnectionPool(startup_nodes=startup_nodes, password=password, decode_responses=True)
        return cls._connection_pool

    @staticmethod
    def init_sentinel_master_client():
        hosts_list = config.get_config("webif.session.sentinel.hosts")
        password = config.get_config("webif.session.sentinel.password")
        master_name = config.get_config("webif.session.sentinel.master_name")
        master_db = config.get_config("webif.session.sentinel.master_db", 1)
        sentinel_list = [(item.split(":")[0], int(item.split(":")[1])) for item in hosts_list]
        redis_sentinel = Sentinel(sentinel_list, password=password)
        return redis_sentinel.master_for(master_name, db=master_db, decode_responses=True)

    @property
    def hgetall_script(self):
        if self._hgetall_script:
            return self._hgetall_script
        lua = """
                local flat_map = redis.call("hgetall", KEYS[1])
                -- local _fail_count = redis.call("hget", KEYS[1], "_fail_count")
                if next(flat_map) == nil then
                    return {}
                end
                -- if type(_fail_count) == "string" and tonumber(_fail_count) >= tonumber(ARGV[2]) then
                --     return flat_map
                -- end
                -- redis.call("expire", KEYS[1], ARGV[1])
                return flat_map
            """
        self._hgetall_script = self.client.register_script(lua)
        return self._hgetall_script

    @property
    def client(self):
        if not self._client:
            enable_sentinel = config.get_config("webif.session.sentinel.enable", False)
            if enable_sentinel:
                self._client = self.init_sentinel_master_client()
                return self._client
            enable_cluster = config.get_config("webif.session.cluster.enable", False)
            connection_pool = self.init_cluster_connection_pool() if enable_cluster else self.init_connection_pool()
            if connection_pool is None:
                return None
            self._client = rediscluster.RedisCluster(connection_pool=connection_pool) if enable_cluster else redis.Redis(connection_pool=connection_pool)
        return self._client

    def hmset(self, uid, session_id, cache_value=None, add_sid=True, renew_ttl=True):
        u_key = self.db_key(uid, 'uid')
        s_key = self.db_key(session_id)
        pipe = self.client.pipeline()
        if cache_value:
            pipe.hset(s_key, mapping=cache_value)
            if add_sid:
                pipe.lpush(u_key, session_id)  # 改用list记录用户登录过的session_id
        if renew_ttl:
            expire_seconds = (cache_value or {}).get('customer_session_expire') or self.EXPIRE_SECONDS
            pipe.expire(u_key, expire_seconds)
            pipe.expire(s_key, expire_seconds)
        pipe.execute()

    def direct_hmset(self, session_id, cache_value):
        flat_map = []
        for key, value in cache_value.items():
            flat_map.append(key)
            flat_map.append(value)
        flat_map.append(self.EXPIRE_SECONDS)
        self.hmset_script(keys=[session_id], args=flat_map)

    @property
    def hmset_script(self):
        if self._hmset_script:
            return self._hmset_script
        lua = """
                local seconds = table.remove(ARGV, #ARGV)
                redis.call("hmset", KEYS[1], unpack(ARGV))
                redis.call("expire", KEYS[1], seconds)
            """
        self._hmset_script = self.client.register_script(lua)
        return self._hmset_script

    def hgetall(self, session_id):
        flat_map = self.hgetall_script(keys=[self.db_key(session_id)])
        session_map = {}
        for i in range(0, len(flat_map), 2):
            session_map[flat_map[i]] = flat_map[i + 1]
        return session_map

    def llen(self, key, key_type='uid'):
        """获取uid key的长度, 同时控制该key的长度在配置限制次数"""
        key = self.db_key(key, key_type)
        pipe = self.client.pipeline()
        pipe.llen(key)
        pipe.ltrim(key, 0, self.ONLINE_LIMIT)
        length = pipe.execute()[0]
        return length

    def get_latest_session_id(self, uid):
        return self.client.lindex(self.db_key(uid, 'uid'), 0)

    def get_session_ids(self, uid):
        return self.client.lrange(self.db_key(uid, 'uid'), 0, -1)

    def get_wrong_password_times(self, user_db_key):
        return self.client.lrange(user_db_key, 0, -1)

    def pop_key_items(self, key, items):
        pipe = self.client.pipeline()
        for item in items:
            pipe.lrem(key, 0, item)
        pipe.execute()

    def delete_keys(self, keys):
        pipe = self.client.pipeline()
        for key in keys:
            pipe.delete(key)
        pipe.execute()

    def pop_sids(self, uid, sids):
        key = self.db_key(uid, 'uid')
        pipe = self.client.pipeline()
        for sid in sids:
            pipe.lrem(key, 0, sid)
        pipe.execute()

    @classmethod
    def db_key(cls, id_str, id_type='session'):
        prefix = '{}:{}'.format(cls.session_prefix, id_type)
        if id_str.startswith(prefix):
            return id_str
        else:
            return "{}:{}".format(prefix, id_str)

    def get_lock(self, key, value=1, exp=60):
        key = render_key(f'trident_lock_{key}')
        return bool(self.client.set(key, value, ex=exp, nx=True))


class FileDriver(object):
    EXPIRE_SECONDS = config.get_config("webif.session.expire_seconds", 24 * 60 * 60)
    _client = None
    session_base_path = os.path.join(project_root, 'data/session_dir')

    @property
    def client(self):
        return self._client

    @classmethod
    def init_session_path(cls):
        if not os.path.exists(cls.session_base_path):
            try:
                os.mkdir(cls.session_base_path)
            except Exception as e:
                logging.exception(e)

    def hmset(self, session_id, cache_value):
        self.init_session_path()
        session_path = os.path.join(self.session_base_path, session_id)
        cache_value['timestamp'] = generate_timestamp()
        with open(session_path, 'w') as open_file:
            pickle.dump(cache_value, open_file)

    def hgetall(self, session_id):
        session_path = os.path.join(self.session_base_path, session_id)
        if not os.path.exists(session_path):
            return {}

        with open(session_path, 'rb') as open_file:
            session_map = pickle.load(open_file)
            if 'timestamp' not in session_map:
                return session_map
            else:
                current = generate_timestamp()
                if current - session_map['timestamp'] > self.EXPIRE_SECONDS:
                    self.delete(session_id)
                    return {}
                else:
                    return session_map

    def delete(self, session_id):
        session_path = os.path.join(self.session_base_path, session_id)
        if os.path.exists(session_path):
            os.remove(session_path)


class SessionManager(object):
    SESSION_ID_NAME = 'trident_session_id'
    SINGLE_SIGN_LIMIT = config.get_config('webif.session.single_sign_limit', False)
    CHECK_PASSWORD_WRONG_TIMES = config.get_config('webif.session.check_wrong_password_times.enable', False)
    COOKIE_EXPIRES_DAYS = config.get_config("webif.session.cookie_expire_days", 7)
    RENEW_TTL = config.get_config("webif.session.renew_ttl", True)

    def __init__(self, handler):
        self.handler = handler
        self._driver = None
        self._session_id = None
        self._cache_map = {}
        self._session_map = None

    @property
    def driver(self):
        if self._driver is None:
            self._driver = RedisDriver()
        return self._driver

    @staticmethod
    def _sha256_hex(value=''):
        if not value:
            value = str(uuid4())
        return sha256(value.encode()).hexdigest()

    @property
    def uid(self):
        """优先从缓存中取uid, 取不到再从cookie里拿"""
        user_id = self._cache_map.get('proxy_user_id')
        if user_id is not None:
            return self._sha256_hex(f'{user_id}')
        return self.handler.get_cookie("{}_uid".format(RedisDriver.session_prefix), self._sha256_hex('-1'))

    @property
    def session_id(self):
        # 先从浏览器cookie中取session_id
        session_id = (
            self.handler.get_cookie(self.SESSION_ID_NAME)
            or self.handler.request.headers.get('X-trident-id', None)
            or self.handler.get_query_argument('session_id', None)
        )

        # 单点登录限制
        # 从当前cookie中取出session id与redis中比较, 相同则返回, 不同则说明发生了新的登录动作, 需要重新生成一个session_id
        if self.SINGLE_SIGN_LIMIT:
            if session_id and self.driver.hgetall(session_id):
                return session_id
            # last_sid = self.driver.get_latest_session_id(self.uid)
            # if not last_sid or last_sid == session_id:
            #     return session_id

        # 默认不做单点登录限制，只要cookie能拿到session_id就直接返回
        else:
            if session_id:
                return session_id

        # 返回缓存的session_id
        if self._session_id:
            return self._session_id

        # 如果从浏览器和缓存都没有拿到session_id，则需要重新生成
        self._session_id = self._sha256_hex()
        self.handler.set_cookie(self.SESSION_ID_NAME, self._session_id, httponly=True, expires_days=self.COOKIE_EXPIRES_DAYS)
        return self._session_id

    @property
    def session_map(self):
        if self._session_map is None:
            self._session_map = self.driver.hgetall(self.session_id)
        return self._session_map

    def __setitem__(self, key, value):
        self._cache_map[key] = value

    def __getitem__(self, key):
        value = self._cache_map.get(key)
        if not value:
            return self.session_map.get(key)
        return value

    @property
    def online_count(self):
        """用户在线会话数"""
        return self.driver.llen(self.uid)

    def clear(self, uid: str, sid: str):
        db_uid = self.driver.db_key(uid, 'uid')
        if sid is None:
            keys = [db_uid] + [self.driver.db_key(i, 'session') for i in self.driver.get_session_ids(uid)]
        else:
            self.driver.pop_sids(uid, [sid])  # delete current session id
            keys = [self.driver.db_key(sid, 'session')]
        self.driver.delete_keys(keys)

    @classmethod
    def generate_uid(cls, user_id):
        return cls._sha256_hex(f'{user_id}')

    def add_or_update(self):
        user_id = self._cache_map.get('proxy_user_id')
        login_operate_flag = user_id is not None
        if login_operate_flag:
            uid = self.generate_uid(user_id)
            pre_uid = self.handler.get_cookie("{}_uid".format(RedisDriver.session_prefix))
            if pre_uid and pre_uid != uid:
                self.driver.pop_sids(pre_uid, [self.session_id])

            self.handler.set_cookie("{}_uid".format(self.driver.session_prefix), uid, httponly=True)
            if self._cache_map:
                session_map = self.driver.hgetall(self.session_id)
                session_map.update(self._cache_map)
                self.driver.hmset(uid, self.session_id, session_map)

        del_sids = []
        for sid in self.driver.get_session_ids(self.uid):
            session_map = self.driver.hgetall(sid)
            if not session_map:
                # session已过期，需要从uid列表清掉记录
                del_sids.append(sid)
                continue
            session_map.update(self._cache_map)
            if sid == self.session_id:
                # 同session更新内容、刷新过期时间
                self.driver.hmset(self.uid, sid, session_map, add_sid=False, renew_ttl=self.RENEW_TTL)
            else:
                # 只有登录操作时，才将之前的设为需登出状态
                if self.SINGLE_SIGN_LIMIT and login_operate_flag:
                    session_map['single_sign_logout'] = '1'
                # 不同session只更新内容，不刷新过期时间
                self.driver.hmset(self.uid, sid, session_map, add_sid=False, renew_ttl=False)

        if del_sids:
            self.driver.pop_sids(self.uid, del_sids)
        if user_id is None:
            # 用于验证码，未登录时候并没有uid，但是该信息需要保存到对应session_id里
            self.set()

    def is_single_sign(self, session_id):
        session_map = self.driver.hgetall(session_id)
        return session_map.get('single_sign_logout') == '1'

    def single_logout(self):
        if not self.SINGLE_SIGN_LIMIT:
            return False
        # 从浏览器cookie中取session_id
        session_id = self.handler.get_cookie(self.SESSION_ID_NAME)
        if not session_id:
            return False
        res = self.is_single_sign(session_id)
        if res:
            self.clear(self.uid, session_id)
            self.driver.pop_sids(self.uid, [session_id])
        return res

    def set(self):
        if not self._cache_map:
            return
        session_map = self.driver.hgetall(self.session_id)
        session_map.update(self._cache_map)
        self.driver.direct_hmset(self.driver.db_key(self.session_id), session_map)

    def get_user_db_key(self, user_id):
        return render_key(self._sha256_hex(f'trident:password:{user_id}'))

    def get_expired_lock_time_key(self, user_id=None, user_db_key=None):
        if not user_db_key:
            user_db_key = self.get_user_db_key(user_id)
        return render_key(hashlib.md5(user_db_key.encode()).hexdigest())

    def check_wrong_password_times(self, user_id):
        if not self.CHECK_PASSWORD_WRONG_TIMES:
            return
        limit_time = config.get_config('webif.session.check_wrong_password_times.limit_seconds', 3600)
        lock_expired_seconds = config.get_config('webif.session.check_wrong_password_times.lock_expired_seconds', 1800)
        user_db_key = self.get_user_db_key(user_id)
        expired_lock_time_key = self.get_expired_lock_time_key(user_db_key=user_db_key)

        # 账号锁定期间，直接跳过
        if self.driver.client.get(expired_lock_time_key):
            return

        deleted_times = []
        current_time = generate_timestamp()
        filter_wrong_times = [current_time]
        wrong_times = self.driver.get_wrong_password_times(user_db_key) or []
        for item in wrong_times:
            if int(item) >= current_time - limit_time:
                filter_wrong_times.append(item)
            else:
                deleted_times.append(item)
        # 清除失效的时间
        if deleted_times:
            self.driver.pop_key_items(user_db_key, deleted_times)

        if len(filter_wrong_times) >= 5:
            # 设置账号锁定时间
            self.driver.client.set(expired_lock_time_key, current_time + lock_expired_seconds, ex=lock_expired_seconds)
            # 清除所有密码错误时间
            self.driver.delete_keys([user_db_key])
        else:
            self.driver.client.lpush(user_db_key, current_time)

    def account_locked(self, user_id):
        if not self.CHECK_PASSWORD_WRONG_TIMES:
            return False
        expired_lock_time_key = self.get_expired_lock_time_key(user_id=user_id)
        return self.driver.client.get(expired_lock_time_key)

    def clear_wrong_password_keys(self, user_id):
        if not self.CHECK_PASSWORD_WRONG_TIMES:
            return
        user_db_key = self.get_user_db_key(user_id)
        expired_lock_time_key = self.get_expired_lock_time_key(user_db_key=user_db_key)
        self.driver.delete_keys([user_db_key, expired_lock_time_key])


def create_mixin(handler):
    attr = '__session_manager'
    if not hasattr(handler, attr):
        setattr(handler, attr, SessionManager(handler))
    return getattr(handler, attr)


class SessionMixin(object):
    @property
    def session(self):
        return create_mixin(self)

    def session_clear(self, uid=None):
        self.session._cache_map = {}  # pylint:disable=protected-access
        if uid is None:
            # delete current uid and session info
            uid = self.session.uid
            sid = self.session.session_id
        else:
            # delete selected uid and all related session info
            uid = str(uid)
            sid = None
        self.session.clear(uid, sid)

    def session_commit(self):
        self.session.add_or_update()
