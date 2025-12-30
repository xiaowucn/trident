import logging

from user_proxy import config

from xmltodict import parse
try:
    from urllib import urlopen
except ImportError:
    from urllib.request import urlopen


def get_user_info(user_api=None):
    if user_api is None:
        user_api = config.get_config('guosen_auth.USER_API')
        if not user_api:
            logging.error('guosen USER_API not config')
            return False, None
    try:
        xml_string = urlopen(user_api).read().strip().decode('utf8', 'ignore')
        logging.info('user xml string: %s', xml_string)
        xml_from_dict = parse(xml_string)
    except ValueError as e:
        logging.exception(e)
        return False, None
    if xml_from_dict.get('user') == 'EMPTY':
        return False, None
    return True, {key.lstrip('@'): value for key, value in xml_from_dict['user'].items()}
