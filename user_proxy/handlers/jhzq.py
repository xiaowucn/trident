# -*-coding:utf-8-*-
import logging

import requests

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.handlers.base import route, permission_auth, BaseHandler
from user_proxy.handlers.forms import DateSearchForm
from user_proxy.models.criteria import Pagination
from user_proxy.models.user import VisitRecord, User, VisitSys
from user_proxy.utils.cas import create_url


@route(r'/jhzq/manage-records')
class JHZQManageRecordsHandler(BaseHandler):
    @permission_auth([User.P_MANAGE])
    def get(self, *args, **kwargs):
        form = DateSearchForm.from_json(self.request.arguments)
        if not form.validate():
            return self.error(self.form_errors_to_str(form.errors))
        if not self.current_user.is_sys_admin:
            return self.error('permission denied', status_code=403)

        start_utc = form.start_utc.data
        end_utc = form.end_utc.data
        cond = VisitRecord.visit_sys == VisitSys.USER_MANAGE.value
        if start_utc is not None:
            cond &= VisitRecord.created_utc >= start_utc
        if end_utc is not None:
            cond &= VisitRecord.created_utc < end_utc

        records_query = db_session.query(VisitRecord).filter(cond).order_by(VisitRecord.id.desc())
        return self.data(Pagination(records_query).limit(form.page.data, form.size.data).data())


@route(r'/jhzq/custom-logs')
class JHZWCustomLogHandler(BaseHandler):
    AUTODOC_OPERATE_CUSTOM_ACTION = 8
    @permission_auth([User.P_MANAGE])
    def get(self, *args, **kwargs):
        form = DateSearchForm.from_json(self.request.arguments)
        if not form.validate():
            return self.error(self.form_errors_to_str(form.errors))
        if not self.current_user.is_sys_admin:
            return self.error('permission denied', status_code=403)
        user_log_url = config.get_config('custom.user_log_url')
        if not user_log_url:
            return self.error('user_log_url not config')
        try:
            url_args = [('action', self.AUTODOC_OPERATE_CUSTOM_ACTION)]
            if form.page.data:
                url_args.append(('page', form.page.data))
            if form.size.data:
                url_args.append(('size', form.size.data))
            if form.start_utc.data:
                url_args.append(('start_utc', form.start_utc.data))
            if form.end_utc.data:
                url_args.append(('end_utc', form.end_utc.data))
            url = create_url(user_log_url, None, *url_args)
            logging.info('get user_log from autodoc url: %s', url)
            response = requests.get(url, verify=False, timeout=3)
            if response.status_code != 200:
                return self.error(f'get autodoc custom user_log error, status_code: {response.status_code}')
            return self.data(response.json()['data'])
        except Exception as e:
            logging.exception(e)
        return self.error('service unavailable')