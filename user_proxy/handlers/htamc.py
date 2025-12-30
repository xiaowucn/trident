# -*-coding:utf-8-*-
from user_proxy.common.rpc_web_service.common import ResultType
from user_proxy.handlers.base import BaseHandler, route, common_token_auth
from user_proxy.web_services.htamc_service import HTAMCWebService


@route(r'/htamc/user/project-info')
class HTAMCUserProjectInoHandler(BaseHandler):
    @common_token_auth
    def post(self):
        data = self.get_json_body(binary=False)
        ext_uname = data.get('user_id')
        project_info = HTAMCWebService.get_user_project_info(ext_uname)
        return self.hand_out_data(project_info)


@route(r'/htamc/sso-login')
class HTAMcSSOLoginHandler(BaseHandler):
    def get(self, *args, **kwargs):  # pylint:disable=too-many-locals
        iv_user = self.request.headers.get('iv-user')
        system = self.get_argument('sys', '')
        # 子系统api调用
        user_id = self.get_argument('userId', None)
        user_name = self.get_argument('userName', None)
        app = self.get_argument('app', '')
        origin = self.get_argument('origin', None)
        if iv_user:
            sys_code = self.get_cookie('sysCode')
        else:
            sys_code = self.get_argument('sysCode', 'atoms')

        ip_address = self.request.headers.get('x-forwarded-for')
        project_id = self.get_argument('projectId', None)
        task_id = self.get_argument('runId', None)
        confirm_tasktype = self.get_argument('confirm_tasktype', None)
        res = HTAMCWebService.sso_login(
            iv_user=iv_user,
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
            user_name=user_name,
            sys_code=sys_code,
        )
        if res[0] == ResultType.REDIRECT_PLUS.value:
            data, _ = res[1]
            self.session['proxy_user_id'] = str(data['user_id'])
            return self.hand_out_data(res)
        return self.hand_out_data(res)


@route(r'/htamc/user/custom-system')
class HTAMCUserCustomSystemHandler(BaseHandler):
    @common_token_auth
    def post(self):
        data = self.get_json_body(binary=False)
        ext_uname = data.get('user_id')
        res = HTAMCWebService.get_user_custom_system(ext_uname)
        return self.hand_out_data(res)
