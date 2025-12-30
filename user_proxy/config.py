import logging
import os
import re
import sys
import base64

import _pickle as pickle
import yaml  # pylint: disable=wrong-import-order

P_PG_SCHEMA = re.compile(r"-c\s+search_path=(\w+)", re.ASCII)

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_usr_config_file = '{}/config/config-usr.yml'.format(project_root)
_config_data = None
env_config_prefix = 'TRIDENT_CONFIG_'
ENV = os.environ.get("ENV")

PREDEFINED_VARS = {
    "project_root": project_root,
}


class ConfigConfusion:
    config_file = '{}/config/config-{}.yml'.format(project_root, os.environ.get('ENV') or 'dev')
    confusion = False

    @classmethod
    def init(cls):
        if os.path.isfile(cls.config_file):
            return

        cls.config_file = cls.config_file[:-4] + ".ctc"
        cls.confusion = True


ConfigConfusion.init()

def get_pg_schema(db_key="webif.postgresql"):
    options = get_config(f"{db_key}.options")
    if options:
        match = P_PG_SCHEMA.search(options)
        if match:
            schema = match.group(1).lower()
            if schema != "public":
                return schema
    return None


def path(*args):
    return os.path.join(project_root, *args)


def _merge(default, usr):
    def __merge(default, usr):
        if isinstance(default, dict) and isinstance(usr, dict):
            for k, v in usr.items():
                if k in default:
                    if isinstance(v, dict):
                        __merge(default[k], v)
                    else:
                        default[k] = v
                else:
                    default[k] = v

    __merge(default, usr)
    return default


def load_confusion(data=None, path_param=None):
    from user_proxy.common.crypto_util import aes_decrypt

    if path_param:
        data = open(path_param, 'rb').read()
    return pickle.loads(aes_decrypt(base64.decodebytes(data), key='cc3ac4a40602f9a5c7a55c13ba057835'))


def smart_load(path_param=None):
    path_param = path_param or ConfigConfusion.config_file
    if path_param.endswith(".ctc"):
        return load_confusion(path_param=path_param)
    return yaml.load(open(path_param, encoding='utf8'), Loader=yaml.FullLoader)


def load_config():
    global _config_data  # pylint: disable=global-statement
    if not _config_data:
        with open(ConfigConfusion.config_file) as stream:
            # logging.error("using config file: %s", ConfigConfusion.config_file)
            _config_data = smart_load(ConfigConfusion.config_file)

        if os.path.isfile(_usr_config_file):
            with open(_usr_config_file, 'r') as stream:
                # logging.error("merging user config: %s", _usr_config_file)
                _config_data = _merge(_config_data, yaml.load(stream, Loader=yaml.FullLoader))
    return _config_data


def fill_vars(value):
    if isinstance(value, (str, bytes)):
        value = value.format(**PREDEFINED_VARS)
    return value


def replace_value_by_environ(ret, env_name):
    if not isinstance(ret, dict):
        envs = {k.upper(): v for k, v in os.environ.items()}
        if env_name in envs:
            ret = yaml.load(envs[env_name], Loader=yaml.FullLoader)
        return ret
    for key, value in ret.items():
        sub_env_name = '{}_{}'.format(env_name, key.upper())
        ret[key] = replace_value_by_environ(value, sub_env_name)
    return ret


def get_config(key_string="", default=None, _load_config=load_config):
    env_name = '{}{}'.format(env_config_prefix, key_string.replace('.', '_').upper())
    _load_config()
    ret = _config_data
    keys = [key.strip() for key in key_string.split(".") if key]
    for key in keys:
        ret = ret.get(key) if isinstance(ret, dict) else None
    ret = replace_value_by_environ(ret, env_name)
    if ret is None:
        return fill_vars(default)
    return fill_vars(ret)


def init_setup():
    if sys.argv[0].endswith("inv") or sys.argv[0].endswith("invoke"):
        return
    log_level = get_config("logging.level", "info")  # only info/debug is allowed
    logging.basicConfig(
        level=logging.INFO if log_level == "info" else logging.DEBUG,
        format="%(asctime)s - [%(levelname)s] [%(threadName)s] (%(module)s:%(lineno)d) %(message)s",
    )
    logging.info("using config file: %s", ConfigConfusion.config_file)


def dump_confusion(data, path_param=None):
    from user_proxy.common.crypto_util import aes_encrypt

    data = base64.encodebytes(aes_encrypt(pickle.dumps(data), key='cc3ac4a40602f9a5c7a55c13ba057835'))
    if not path_param:
        return
    with open(path_param, 'wb') as cfile:
        cfile.write(data)


def yml2ctc():
    load_config()
    dump_confusion(_config_data, ConfigConfusion.config_file[:-4] + ".ctc")


class ConfigValue:
    def __init__(self, *args):
        self._args = args
        self._old = []

    def __enter__(self):
        for dot_sep_key, val in self._args:
            try:
                keys, last_key = dot_sep_key.rsplit(".", 1)
                dct = get_config(keys)
            except ValueError:
                last_key = dot_sep_key
                dct = _config_data
            self._old.append((dct, last_key, dct[last_key]))
            dct[last_key] = val

    def __exit__(self, exc_type, exc_val, exc_tb):
        for dct, key, val in self._old:
            dct[key] = val


init_setup()

if __name__ == "__main__":
    yml2ctc()
