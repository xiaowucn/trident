# -*-coding:utf-8-*-
import ssl

from suds.client import Client


def process_suds_location(url):
    if url.endswith('?wsdl'):
        return url[:-5]
    return url


def get_suds_client(webservice_url, **kwargs):
    if hasattr(ssl, '_create_unverified_context'):
        ssl._create_default_https_context = ssl._create_unverified_context  # pylint: disable=protected-access
    location = process_suds_location(webservice_url)
    client = Client(webservice_url, location=location, **kwargs)
    return client
