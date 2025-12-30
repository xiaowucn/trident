# -*-coding:utf-8-*-
from sqlalchemy.orm.attributes import flag_modified

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.handlers.base import route, BaseHandler
from user_proxy.models.user import User


@route(r'/user/user-data')
class UserCasLogoutHandler(BaseHandler):
    def post(self, *args, **kwargs):
        if not config.get_config('webif.debug', False):
            return self.error('config is disable', status_code=404)
        data = self.get_json_body(binary=False)
        user_id = data.get('user_id')
        user = db_session.query(User).filter(User.id == user_id).first()
        if not user:
            return self.error('用户不存在')
        user_data = data.get('user_data', {})
        user.user_data.update(user_data)
        flag_modified(user, 'user_data')
        db_session.commit()

        return self.data(user.to_dict())

@route(r'/debug/ha-verify')
class HAVerifyHandler(BaseHandler):
    def get(self, *args, **kwargs):
        res = {
            'res': 'ok',
        }
        try:
            db_session.query(User).filter(User.id > 0).first()
        except Exception as e:
            res['query'] = str(e)

        return self.data(res, binary=False)
