import json
import logging
import traceback
import urllib.parse
from typing import Dict
from xml.dom.minidom import parseString
from xml.etree.ElementTree import Element, SubElement, tostring

import requests
from sqlalchemy.orm.attributes import flag_modified
from utensils.auth.token import encode_url

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.models.user import User, Department
from user_proxy.worker.app import app


class WebServiceBase:
    @staticmethod
    def make_node(name, children=None, **attrs) -> Element:
        children = children or {}
        body = Element(name)
        for key, value in attrs.items():
            body.attrib[key] = value
        for key, value in children.items():
            child = SubElement(body, key)
            child.text = str(value)
        return body

    @classmethod
    def generate_xml(cls, request_body):
        xml = cls.make_node(
            'soapenv:Envelope',
            **{
                'xmlns:soapenv': "http://schemas.xmlsoap.org/soap/envelope/",
                'xmlns:out': "http://out.webservice.organization.sys.kmss.landray.com/",
            },
        )
        xml.append(cls.make_node('soapenv:Header'))
        body = cls.make_node('soapenv:Body')
        xml.append(body)
        request = cls.make_node('out:getElementsBaseInfoForPD')
        body.append(request)
        request.append(cls.make_node('arg0', children=request_body))
        xml_bytes = tostring(xml)
        return xml_bytes

    @classmethod
    def connect_webserver(cls, url, data):
        headers = {
            'Content-Type': 'text/xml;charset=utf-8',
            'Accept': 'text/xml;charset=utf-8',
        }
        response = requests.post(url=url, data=data, headers=headers, verify=False)
        xml_dom = parseString(response.content)
        count = xml_dom.getElementsByTagName('count')[0].childNodes[0].data
        message = xml_dom.getElementsByTagName('message')[0].childNodes[0].data
        return_state = xml_dom.getElementsByTagName('returnState')[0].childNodes[0].data
        return {'count': int(count), 'message': message, 'returnState': int(return_state)}


class UpdateDepartmentData:
    @staticmethod
    def create_update_url(target):
        send_url = target['department_url']
        url = encode_url(send_url, target['app_id'], target['secret_key'], exclude_domain=True)
        logging.info('update autodoc department url: %s', url)
        return url

    @classmethod
    def update_autodoc_department(cls, data):
        logging.info('post department data to autodoc')
        target = config.get_config('unify_auth.auth_config.auth_autodoc_overall')
        if not target:
            logging.error("unify_auth auth_autodoc_department_sync not config")
        url = cls.create_update_url(target)
        try:
            res = requests.post(url, json=data)
            if not res.ok:
                logging.error("update autodoc department err, err: %s", res.text)
            else:
                logging.info("update autodoc department success")
        except Exception as e:
            logging.error(traceback.format_exc())


def parse_department_info(department_info_dict):
    department_list = department_info_dict.get('message')
    # logging.info('department_list_type=%s, department_list=%s', type(department_list), department_list)
    if isinstance(department_list, str):
        department_list = json.loads(department_list)

    departments = db_session.query(Department).filter(Department.external_id.isnot(None)).all()
    exists_departments: Dict[str, Department] = {depart.external_id: depart for depart in departments}

    for item in department_list:
        if not item['isAvailable']:
            logging.info('department_id=%s, department_name=%s is not available', item['id'], item['name'])
            continue
        dept_ins = exists_departments.pop(item['id'], Department(external_id=item['id']))
        dept_ins.parent_id = item.get('parent', '')
        dept_ins.name = item['name']
        dept_ins.data = dept_ins.data or {}
        dept_ins.data.update(item)
        flag_modified(dept_ins, 'data')
        db_session.add(dept_ins)

    # 删除不是同步的department
    for model in exists_departments.values():
        logging.info('delete not exist in sync department: dept_id=%s, name=%s', model.external_id, model.name)
        model.deleted = 1
    db_session.commit()


def parse_user_info(user_info_dict):
    user_list = user_info_dict.get('message')
    # logging.info('user_list_type=%s, user_list=%s', type(user_list), user_list)
    if isinstance(user_list, str):
        user_list = json.loads(user_list)

    db_users = db_session.query(User).filter(User.deleted == 0).all()
    sync_user_names = set()
    department_dict = {item.external_id: item.name for item in db_session.query(Department).all()}
    for item in user_list:
        if not item['isAvailable']:
            logging.info('ext_uname=%s, username=%s is not available', item['loginName'], item['name'])
            continue
        department_name = department_dict.get(item['parent']) or ''
        User.make_user(item['id'], item['loginName'], department=department_name, department_id=item['parent'], username=item['name'])
        sync_user_names.add(item['loginName'])

    for db_user in db_users:
        if db_user.oa_user and db_user.ext_uname not in sync_user_names:
            logging.info('delete not exist in sync user: ext_uname=%s', db_user.ext_uname)
            db_user.deleted = 1
    db_session.commit()


@app.task
def sync_dept_user_from_webservice():
    base_url = config.get_config('customer_uri_info.base_server')
    sync_api = config.get_config('customer_uri_info.sync_dept_user_uri')
    sync_url = urllib.parse.urljoin(base_url, sync_api)
    try:
        dept_parameter_data = WebServiceBase.generate_xml({'returnOrgType': '[{"type":"dept"}]'})
        user_parameter_data = WebServiceBase.generate_xml({'returnOrgType': '[{"type":"person"}]'})
        department_info = WebServiceBase.connect_webserver(sync_url, dept_parameter_data)
        user_info = WebServiceBase.connect_webserver(sync_url, user_parameter_data)
    except ConnectionError as e:
        logging.info('can not connect web service: %s', e)
        return
    logging.info('connect service succeed, extracting data')
    if department_info.get('returnState') != 2:
        logging.error('parse department info error, returnState=%s', department_info.get('returnState'))
        return
    parse_department_info(department_info)
    logging.info('extract department_info completed')
    if user_info.get('returnState') != 2:
        logging.error('parse user info error, returnState=%s', user_info.get('returnState'))
        return
    parse_user_info(user_info)
    logging.info('extract user_info completed')
    UpdateDepartmentData.update_autodoc_department(department_info)


if __name__ == '__main__':
    sync_dept_user_from_webservice()
