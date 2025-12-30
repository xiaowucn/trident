from utensils.auth.token import encode_url as _encode_url
from utensils.auth.token import revise_url, generate_timestamp, encode_url_path, validate_token_url

from user_proxy import config

revise_url = revise_url
generate_timestamp = generate_timestamp
encode_url_path = encode_url_path


def validate_url(url, app_id=None, secret_key=None, token_expire=None, exclude_domain=True):
    app_id = app_id or config.get_config("unify_auth.auth_self.app_id")
    secret_key = secret_key or config.get_config("unify_auth.auth_self.secret_key")
    token_expire = token_expire or config.get_config("unify_auth.auth_self.token_expire") or 3600
    return validate_token_url(url, app_id, secret_key, token_expire, exclude_domain=exclude_domain)


def encode_url(*args, exclude_domain=False, **kwargs):
    return _encode_url(*args, exclude_domain=exclude_domain, **kwargs)


def encode_url_by_config(appname, url, exclude_domain=False):
    app_id = config.get_config("unify_auth.auth_config.auth_%s.app_id" % appname)
    secret_key = config.get_config("unify_auth.auth_config.auth_%s.secret_key" % appname)
    return encode_url(url, app_id, secret_key, exclude_domain=exclude_domain)
