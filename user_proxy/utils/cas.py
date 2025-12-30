# pylint:disable=too-many-positional-arguments
import json
import logging
import ssl
import subprocess
from urllib.parse import quote, urlencode, urljoin
from urllib.request import urlopen

import requests
from xmltodict import parse

from user_proxy import config


def create_url(base, path, *query):
    url = base
    if path is not None:
        url = urljoin(url, quote(path))
    query = filter(lambda pair: pair[1] is not None, query)
    if query:
        delimiter = '&' if "?" in url else "?"
        url = urljoin(url, '{}{}'.format(delimiter, urlencode(list(query))))
    return url


def create_cas_login_url(cas_server, cas_uri, service, renew=None, gateway=None, appid=None):
    return create_url(
        cas_server,
        cas_uri,
        ('service', service),
        ('renew', renew),
        ('gateway', gateway),
        ('appid', appid),
    )


def create_cas_logout_url(cas_server, cas_uri, service=None):
    return create_url(
        cas_server,
        cas_uri,
        ('service', service),
    )


def create_cas_validate_url(cas_url, cas_route, service, ticket, renew=None, res_format=None):
    return create_url(cas_url, cas_route, ('service', service), ('ticket', ticket), ('renew', renew), ('format', res_format))


def validate(ticket, origin_url, handler):
    cas_username_session_key = config.get_config('cas_auth.cas_username_session_key')
    cas_attributes_session_key = config.get_config('cas_auth.cas_attributes_session_key')
    origin_url = config.get_config('cas_auth.trident_auth_url') or origin_url

    logging.debug("validating token %s", ticket)

    cas_validate_url = create_cas_validate_url(
        config.get_config('cas_auth.internal_server') or config.get_config('cas_auth.server'),  # csc may have internal_server
        config.get_config('cas_auth.validate_uri'),
        origin_url,
        ticket,
        res_format='xml' if config.get_config('sys') == 'piccamc' else None,
    )

    logging.debug("Making GET request to %s", cas_validate_url)

    xml_from_dict = {}
    is_valid = False

    try:
        if hasattr(ssl, '_create_unverified_context'):
            ssl._create_default_https_context = ssl._create_unverified_context  # pylint: disable=protected-access
        if config.get_config('sys') == 'csco':
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            data = {"ticket": ticket, "service": config.get_config('cas_auth.trident_url')}
            xml_dump = requests.post(cas_validate_url, headers=headers, data=data, verify=False, timeout=10).content
        else:
            xml_dump = urlopen(cas_validate_url).read().strip().decode('utf8', 'ignore')
        xml_from_dict = parse(xml_dump)
        logging.debug('cas xml_from_dict: %s', xml_from_dict)
        cas_prefix = config.get_config('cas_auth.cas_prefix', 'cas:')
        is_valid = f"{cas_prefix}authenticationSuccess" in xml_from_dict[f"{cas_prefix}serviceResponse"]
    except ValueError as e:
        logging.exception(e)
        logging.error("CAS returned unexpected result")
        return is_valid, xml_from_dict

    if is_valid:
        logging.debug("valid")
        xml_from_dict = xml_from_dict[f"{cas_prefix}serviceResponse"][f"{cas_prefix}authenticationSuccess"]
        username = xml_from_dict[f"{cas_prefix}user"]
        handler.set_secure_cookie(cas_username_session_key, username)

        if f"{cas_prefix}attributes" in xml_from_dict:
            attributes = xml_from_dict[f"{cas_prefix}attributes"]

            if f"{cas_prefix}memberOf" in attributes:
                attributes[f"{cas_prefix}memberOf"] = attributes[f"{cas_prefix}memberOf"].lstrip('[').rstrip(']').split(',')
                for group_number in range(0, len(attributes[f'{cas_prefix}memberOf'])):
                    attributes[f'{cas_prefix}memberOf'][group_number] = attributes[f'{cas_prefix}memberOf'][group_number].lstrip(' ').rstrip(' ')
            handler.set_secure_cookie(cas_attributes_session_key, json.dumps(attributes))
    else:
        logging.debug("invalid")

    return is_valid, xml_from_dict


def decrypt_ctsec_token(token: str):
    key = config.get_config('cas_auth.sso_crypt_key')
    if not key:
        logging.error('sso crypt key is null')
        return None

    project_root = config.project_root
    # pylint: disable=subprocess-run-check
    res = subprocess.run(
        ['/usr/bin/java', '-classpath', f'{project_root}/misc/ctsec/cas-sso-client-1.0-SNAPSHOT.jar', 'com.ctsec.sso.OATokenUtil', token, key],
        stdout=subprocess.PIPE,
    )
    if res.returncode == 0:
        decrypted_token = res.stdout
        return decrypted_token.decode()
    logging.error('shell command execution failed')
    return None


if __name__ == '__main__':
    print(
        create_url(
            config.get_config('cas_auth.server'),
            config.get_config('cas_auth.logout_uri'),
            (
                'service',
                create_url(
                    config.get_config('cas_auth.server'),
                    config.get_config('cas_auth.login_uri'),
                ),
            ),
            ('systemName', config.get_config('cas_auth.system_name')),
        )
    )
