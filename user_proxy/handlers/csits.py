# pylint: disable=too-many-locals

import datetime
import logging
from enum import Enum
from uuid import uuid4

import requests

from user_proxy import config
from user_proxy.config import get_config
from user_proxy.db import db_session
from user_proxy.handlers.base import (
    BaseHandler,
    permission_auth,
    route,
    common_token_auth,
)
from user_proxy.models.csits import CsitsTrack
from user_proxy.models.user import User
from user_proxy.web_services import ProxyWebService


class SystemName(Enum):
    GRATER = "银行流水识别与分析"
    PDFLUX = "通用文档与表格识别"


class Event(Enum):
    BROWER = 1
    CLICK = 2
    LOGIN = 3
    LOGOUT = 4


@route(r"/csits/track")
class CsitsTrackHandler(BaseHandler):
    @permission_auth()
    def post(self):
        try:
            self.add_track(user=self.current_user, data=self.get_json_body(binary=False))
        except Exception as e:
            return self.error("埋点接口调用失败")

        return self.data({})

    @staticmethod
    def add_track(user, data: dict):
        account = user.ext_uname
        dept_name = user.user_data.get("full_dept_name")
        dept_id = user.user_data.get("org_dept_id")
        username = user.user_data.get("username")
        user_role = user.user_data.get("user_role")

        uuid = data.get("uuid")
        event_time = data.get("eventTime")
        event = data.get("event")
        url = data.get("url")
        path = data.get("path")
        system_code = data.get("systemCode")
        system_name = data.get("systemName")
        path_from = data.get("pathFrom")

        if data.get("event"):
            track_url = get_config("csits_track.start_api")
            track_data = {
                "uuid": uuid,
                "account": account,
                "deptId": dept_id,
                "deptName": dept_name,
                "userName": username,
                "userRole": user_role,
                "event": event,
                "eventTime": event_time,
                "url": url,
                "path": path,
                "pathFrom": path_from,
                "systemCode": system_code,
                "systemName": system_name,
            }
        else:
            track_url = get_config("csits_track.end_api")
            track_data = {
                "uuid": uuid,
                "eventTime": event_time,
            }

        if track_url:
            try:
                response = requests.post(
                    url=track_url,
                    json=track_data,
                    verify=False,
                    timeout=5,
                    headers={
                        "systemCode": system_code,
                    },
                )

                if response.status_code == 200:
                    res_data = response.json()
                    if not res_data.get("success"):
                        raise Exception(f"{track_url} failed, code: {res_data.get('code') or ''}, msg: {res_data.get('msg') or ''}")
                else:
                    raise Exception(response.status_code)
            except Exception as e:
                logging.exception(e)
                raise e

        track = CsitsTrack(
            uuid=uuid,
            account=account,
            dept_id=dept_id,
            dept_name=dept_name,
            event_time=event_time,
            event=event,
            url=url,
            path=path,
            system_code=system_code,
            system_name=system_name,
        )

        db_session.add(track)
        db_session.commit()

    @staticmethod
    def add_login_track(user: str, url: str, system: str):
        uuid = str(uuid4())
        event = Event.LOGIN.value
        event_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_code = system
        system_name = SystemName[system.upper()].value
        path = "庖丁用户认证系统"

        data = {
            "uuid": uuid,
            "event": event,
            "eventTime": event_time,
            "url": url,
            "path": path,
            "systemCode": system_code,
            "systemName": system_name,
        }

        try:
            CsitsTrackHandler.add_track(user=user, data=data)
        except Exception as e:
            pass


@route(r"/csits/user-info")
class CsitsUserInfoHandler(BaseHandler):
    @common_token_auth
    def get(self, *args, **kwargs):
        if config.get_config("sys") != "csits":
            return self.error("Not found", status_code=404)

        account_no = self.get_argument("account_no")
        uid = ProxyWebService.get_uid_by_acc(account_no)
        if not uid:
            return self.error("User does not exist", status_code=404)
        user = db_session.query(User).filter(User.ext_uname == account_no).first()
        if not user:
            department, department_id, username, user_role, org_dept_id, full_dept_name = ProxyWebService.get_user_info(uid)
            user = User.make_user(
                uid=uid,
                ext_uname=account_no,
                department=department,
                department_id=department_id,
                username=username,
                user_role=user_role,
                _from="cas",
                org_dept_id=org_dept_id,
                full_dept_name=full_dept_name,
            )
        return self.data(user.to_dict())

@route(r"/csits/user-info-by-acc")
class CsitsUserInfoHandler(BaseHandler):
    @common_token_auth
    def get(self, *args, **kwargs):
        if config.get_config("sys") != "csits":
            return self.error("Not found", status_code=404)

        account_no = self.get_argument("account_no")
        user_info = ProxyWebService.get_user_info_by_acc(account_no)
        return self.data(user_info)


@route(r"/csits/org-unit-tree-v36")
class CsitsOrgUnitTreeHandler(BaseHandler):
    @common_token_auth
    def get(self, *args, **kwargs):
        if config.get_config("sys") != "csits":
            return self.error("Not found", status_code=404)

        unit_tree = ProxyWebService.get_org_unit_tree()
        return self.data(unit_tree)


@route(r"/csits/org-user-infos")
class CsitsOrgUserInfosHandler(BaseHandler):
    @common_token_auth
    def get(self, *args, **kwargs):
        if config.get_config("sys") != "csits":
            return self.error("Not found", status_code=404)

        org_id = self.get_argument("org_id")
        user_infos = ProxyWebService.get_org_user_infos(org_id)
        return self.data(user_infos)

@route(r"/csits/user-infos")
class CsitsUserInfosHandler(BaseHandler):
    @common_token_auth
    def get(self, *args, **kwargs):
        if config.get_config("sys") != "csits":
            return self.error("Not found", status_code=404)

        username = self.get_argument("username")
        user_infos = ProxyWebService.get_user_infos(username)
        return self.data(user_infos)
