from invoke import task

from user_proxy.utils.kysec import parse_user_list_from_excel


@task(help={
    'filename': "要导入的人员名单：xlsx格式",
})
def import_user_from_excel(ctx, filename):
    parse_user_list_from_excel(filename)
