import logging
import os
import traceback

from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL
from sqlalchemy.orm.attributes import flag_modified
from suds import sudsobject

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.devtools.sync_user_info import get_department_info, get_department_roles, get_user_info
from user_proxy.models.user import Role, User, Department
from user_proxy.suds_client import get_suds_client
from user_proxy.worker.app import app


def get_remote_db(custom_name='kysec'):
    if config.get_config(f'{custom_name}.enable'):
        try:
            logging.info('remote db connection init. pid:{}'.format(os.getpid()))
            remote_url = URL(drivername='oracle',
                             host=config.get_config(f"{custom_name}.db.host"),
                             port=config.get_config(f"{custom_name}.db.port"),
                             username=config.get_config(f"{custom_name}.db.user"),
                             password=config.get_config(f"{custom_name}.db.password"),
                             database=config.get_config(f"{custom_name}.db.db_name"),
                             query={"charset": 'utf8'})
            return create_engine(remote_url, pool_pre_ping=True)
        except:
            logging.error(traceback.format_exc())


def process_user(user_datas, total_department_info, departments_map):
    exist_users = db_session.query(User).all()
    default_role = db_session.query(Role).filter(Role.oa_default.is_(True)).first()
    if not default_role:
        logging.info('do not find os_default roles')
    exist_oa_user = []
    for user in exist_users:
        uid = user.user_data.get('uid', '')
        if uid in user_datas:
            exist_oa_user.append(uid)
            user_data = user.user_data
            origin_department = user_data.get('department', '')
            oa_user_info = user_datas[uid]
            # 更新手动创建且在oa系统的用户信息
            user_data.update(oa_user_info)
            if user_data.get('_from') == 'self':
                user_data['_from'] = 'kysec'
                user_data['is_sync'] = True
            user_data.pop('departmentid', None)

            # 更新部门信息
            department_info = total_department_info.get(oa_user_info['department_id'])
            user_data['display_department'] = (departments_map.get(oa_user_info['department_id']) or {}).get('display_department')
            if not user_data['department'] and user_data['department_id'] and department_info:
                user_data['department'] = department_info.full_name
            if user_data.get('department_id'):
                # 由于客户提供的department_id为int,之前转换过程中,部门id统一转换为int,存储时,转换为str
                user_data['department_id'] = str(user_data['department_id'])
            user.user_data = user_data
            flag_modified(user, 'user_data')

            # 用户已有roles信息,根据department更新user的roles信息
            if not department_info:
                continue
            if origin_department == oa_user_info['department'] and user.user_data.get('roles_modify'):
                continue
            first_level_department_id = department_info.first_level_department_id
            if not first_level_department_id:
                continue
            user_roles = get_department_roles(first_level_department_id, default_role)
            if not user_roles:
                continue
            user.roles = user_roles
        else:
            if user.user_data.get('_from') == 'self' or user.permissions == [User.P_MANAGE]:
                continue
            # 删除不在oa系统且不是手动创建的用户
            db_session.delete(user)
            logging.info('do not sync user info, uid:{}'.format(uid))

    need_create_oa_user = {uid: user_info for uid, user_info in user_datas.items() if uid not in exist_oa_user}
    for uid, user_info in need_create_oa_user.items():
        logging.info('user: %s, department: %s created!', uid, user_info['department'])
        display_department = (departments_map.get(user_info['department_id']) or {}).get('display_department')
        department_id = str(user_info['department_id']) if user_info.get('department_id') else None
        user = User.make_user(
            uid=uid, ext_uname=uid,
            department=user_info['department'], department_id=department_id, is_sync=True,
            username=user_info['username'], work_status=user_info.get('work_status'), display_department=display_department
        )
        # 新建用户为默认角色
        department_info = total_department_info.get(user_info.get('department_id'))
        if not department_info:
            continue
        first_level_department_id = department_info.first_level_department_id
        if not first_level_department_id:
            continue
        user_roles = get_department_roles(first_level_department_id, default_role)
        if not user_roles:
            continue
        user.roles = user_roles

    db_session.commit()
    logging.info('completed')


def process_department(departments_map):
    if not config.get_config('worker.sync_department', False):
        return
    logging.info('save departments begin')
    departments = db_session.query(Department).filter(Department.external_id.isnot(None)).all()
    exists_departments = {depart.external_id: depart for depart in departments}
    for department_id, depart_data in departments_map.items():
        department_ins = exists_departments.pop(
            str(department_id),
            Department(external_id=str(department_id))
        )
        department_ins.parent_id = str(depart_data['_supdepartmentid'])
        department_ins.name = depart_data['_fullname']
        department_ins_data = department_ins.data or {}
        department_ins_data.update(depart_data)
        department_ins.data = department_ins_data
        flag_modified(department_ins, 'data')
        db_session.add(department_ins)
    # 删除不是同步的department
    for model in exists_departments.values():
        logging.info('delete not exist in sync department: dept_id=%s, name=%s', model.external_id, model.name)
        db_session.delete(model)
    db_session.commit()
    logging.info('save departments completed')


@app.task
def sync_user_data_from_webserver():
    url = config.get_config('sync_user_info.uri')
    ip_address = config.get_config('ip_address')
    try:
        client = get_suds_client(url)
        service = client.service
        department_result = service.getHrmDepartmentInfo(ip_address)
        result = service.getHrmUserInfo(ip_address)
    except ConnectionError as e:
        logging.info('can not connect OA service: {}'.format(e))
        return
    logging.info('connect service succeed, extracting data')
    department_list = sudsobject.asdict(department_result).get('DepartmentBean', [])
    fix_department_list = [sudsobject.asdict(department_sudsobject) for department_sudsobject in department_list]
    total_department_info = get_department_info(fix_department_list)
    departments_map = {int(item['_departmentid']): item for item in fix_department_list if item['_departmentid'] is not None}
    logging.info('extract department_info completed')

    user_list = sudsobject.asdict(result).get('UserBean', [])
    fix_user_list = [sudsobject.asdict(user_sudsobject) for user_sudsobject in user_list]
    user_datas = get_user_info(fix_user_list)
    logging.info('sync user info completed, total: {}'.format(len(user_datas)))
    process_user(user_datas, total_department_info, departments_map)
    process_department(departments_map)


@app.task
def sync_user_data_from_customer_db():
    department_sql = config.get_config('kysec.db.department_sql')
    user_sql = config.get_config('kysec.db.user_sql')
    engine = get_remote_db()
    with engine.connect() as connection:
        department_result = connection.execute(department_sql)
        user_result = connection.execute(user_sql)
        fix_department_list = [{"_departmentid": custom_dept.dpid,
                                "_fullname": custom_dept.title,
                                "_shortname": custom_dept.dpabbr,
                                "_supdepartmentid": custom_dept.xdpid or 0,  # 之前接口返回时，一级部门的上级部门id为0， 现在通过数据库查询的方式时，为None
                                "display_department": custom_dept.dptitlepath} for custom_dept in department_result.fetchall()]
        if not fix_department_list:
            logging.error('get department from db error, empty data')
            return
        logging.info('department info eg: %s', fix_department_list[0])
        total_department_info = get_department_info(fix_department_list)
        departments_map = {item['_departmentid']: item for item in fix_department_list}
        logging.info('extract department_info completed')

        fix_user_list = [{"loginid": custom_user.account,
                          "lastname": custom_user.name,
                          "departmentid": custom_user.dpid,
                          "departmentname": custom_user.dptitle,
                          "status": custom_user.status} for custom_user in user_result.fetchall()]

        if not fix_user_list:
            logging.error('get user from db error, empty data')
            return
        logging.info('user info eg: %s', fix_user_list[0])
        user_datas = get_user_info(fix_user_list)
        logging.info('sync user info completed, total: {}'.format(len(user_datas)))
        process_user(user_datas, total_department_info, departments_map)
        process_department(departments_map)


if __name__ == '__main__':
    sync_user_data_from_customer_db()
