from user_proxy import config
from user_proxy.common.rpc_web_service.common import ResultType
from user_proxy.handlers.base import route, BaseHandler, permission_auth
from user_proxy.web_services import HTSCWebService


@route(r'/htsc/sso-login')
class HTSCSSOLoginHandler(BaseHandler):
    def get(self, *args, **kwargs):
        header_key = config.get_config('htsc_auth.header_key')
        user_token = self.request.headers.get(header_key)
        user_id = self.get_argument('userId', None)
        system = self.get_argument('sys', '')
        # autodoc api调用
        app = self.get_argument('app', '')
        ip_address = self.request.headers.get('x-forwarded-for')
        project_id = self.get_argument('projectId', None)
        task_id = self.get_argument('runId', None)
        origin = self.get_argument('origin', None)
        confirm_tasktype = self.get_argument('confirm_tasktype', None)
        res = HTSCWebService.sso_login(
            user_token=user_token,
            user_id=user_id,
            system=system,
            app=app,
            ip_address=ip_address,
            request_path=self.request.path,
            project_id=project_id,
            task_id=task_id,
            confirm_tasktype=confirm_tasktype,
            origin=origin,
            origin_host=self.origin_host,
        )
        if res[0] == ResultType.REDIRECT_PLUS.value:
            data, _ = res[1]
            self.session['proxy_user_id'] = str(data['user_id'])
            return self.hand_out_data(res)
        return self.hand_out_data(res)


@route(r'/htsc/darkroom/sso-login')
class HTSCDarkroomSSOLoginHandler(BaseHandler):
    def get(self, *args, **kwargs):
        header_key = config.get_config('htsc_darkroom_auth.header_key')
        user_token = self.request.headers.get(header_key)
        ip_address = self.request.headers.get('x-forwarded-for')
        system = self.get_argument('sys', '')
        stage_id = self.get_argument('stageId', '')
        stage_type = self.get_argument('stageType', '')
        origin = self.get_argument('origin', '')
        cps = self.get_argument('cps', '')
        res = HTSCWebService.darkroom_sso_login(
            user_token,
            system,
            ip_address,
            request_path=self.request.path,
            origin_host=self.origin_host,
            stage_id=stage_id,
            stage_type=stage_type,
            origin=origin,
            cps=cps,
        )
        if res[0] == ResultType.REDIRECT_PLUS.value:
            data, _ = res[1]
            self.session['proxy_user_id'] = str(data['user_id'])
            return self.hand_out_data(res)
        return self.hand_out_data(res)


@route(r'/htsc/visit-records')
class HTSCVisitRecordsHandler(BaseHandler):
    @permission_auth()
    def get(self, *args, **kwargs):
        res = HTSCWebService.get_visit_records()
        return self.hand_out_data(res)
