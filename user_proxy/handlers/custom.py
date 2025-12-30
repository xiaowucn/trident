import logging
from html import escape

import requests
from aiohttp import ClientSession

from user_proxy import config
from user_proxy.handlers.base import route, BaseHandler, permission_auth
from user_proxy.models.user import VisitRecord, VisitSys
from user_proxy.utils.cas import create_url


@route(r'/faulty-wordings')
class CheckFaultyWordingsHandler(BaseHandler):
    @permission_auth()
    def post(self, *args, **kwargs):
        body = self.get_json_body()
        source_text = body.get('source_text')
        if not source_text:
            return self.error('invalid parameters')
        faulty_wording_api = config.get_config('custom.faulty_wording_api')
        if not faulty_wording_api:
            return self.error('service unavailable')
        VisitRecord.create(self.current_user.id, VisitSys.FAULTY_WORDING.value)
        try:
            response = requests.post(faulty_wording_api, json={'source_text': escape(source_text)})
            return self.data(response.json())
        except Exception as e:
            logging.exception(e)
        return self.error('service unavailable')

@route(r'/copy-records')
class CopyRecordsHandler(BaseHandler):
    @permission_auth()
    async def get(self, *args, **kwargs):
        ext_uname = self.get_argument('ext_uname', None)
        page = self.get_argument('page', 1)
        size = self.get_argument('size', 20)
        if not ext_uname:
            return self.error('ext_uname is required')
        copy_record_api = config.get_config('custom.copy_record_api')
        if not copy_record_api:
            return self.error('service unavailable')
        async with ClientSession() as session:
            try:
                copy_record_url = create_url(
                    copy_record_api, None,
                    ('ext_uname', ext_uname),
                    ('page', page),
                    ('size', size)
                )
                response = await session.get(copy_record_url)
                return self.data(await response.json())
            except Exception as e:
                logging.exception(e)
            return self.error('service unavailable')