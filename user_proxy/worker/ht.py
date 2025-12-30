import datetime
import logging
import sys
import urllib.parse

import requests
from sqlalchemy.orm.attributes import flag_modified
from utensils.util import generate_timestamp

from user_proxy.config import get_config
from user_proxy.db import db_session
from user_proxy.models.user import Department, User
from user_proxy.worker.app import app


class TaskException(Exception):
    pass


class AnduAPI:
    def __init__(self, domain, account, password):

        self.domain = domain
        self.account = account
        self.password = password
        self.session = requests.Session()
        self.session.verify = get_config("command.get_data.ssl_verify", False)
        self.login()

    def login(self):
        rsp = self.session.post(
            f"{self.domain}/UniExServices/restfulapi/token", json={"account": self.account, "password": self.password}
        )
        if rsp.status_code != 200:
            raise TaskException(f"Andu login failed with http_code: {rsp.status_code}")
        rsp = rsp.json()
        if rsp["code"] != "200":
            raise TaskException(f"Andu login failed with code: {rsp['code']}")
        self.token = rsp.get("token")
        if not self.token:
            raise TaskException("Andu login failed with null token")
        self.session.headers.update({"Authorization": self.token})

    def download_file(self, path, auto_relogin=True):

        path = urllib.parse.quote(path, safe='/', encoding='utf-8')
        location = get_config("command.get_data.location", 1)
        url = f"{self.domain}/UniExServices/restfulapi/{self.account}/{path}?method=download&is_dir=false&location={location}"
        rsp = self.session.get(url)
        if rsp.status_code != 200:
            if rsp.status_code == 401 and auto_relogin:
                self.login()
                return self.download_file(path, auto_relogin=False)
            else:
                raise TaskException(f"Andu download file failed with http_code: {rsp.status_code}, {url}")
        return rsp.content


def _build_path(config_path):
    date_policy = get_config("command.get_data.date_policy")
    if not date_policy or not date_policy.startswith("T-"):
        raise TaskException("invalid config command.get_data.date_policy")
    date_offset = int(date_policy[2:])
    date = datetime.date.today() - datetime.timedelta(days=date_offset)
    return config_path.replace('#DATE#', date.strftime(get_config("command.get_data.date_format", "%Y%m%d")))


def _combine_params(domain, account, password, user_path, depart_path):
    domain = domain or get_config("command.get_data.domain")
    account = account or get_config("command.get_data.account")
    password = password or get_config("command.get_data.password")

    user_path = user_path or get_config("command.get_data.fixed_user_path") or _build_path(get_config("command.get_data.user_path"))
    depart_path = depart_path or get_config("command.get_data.fixed_depart_path") or _build_path(get_config("command.get_data.depart_path"))
    return domain, account, password, user_path, depart_path


def load_data_file_func(user_file, dept_file, debug):
    import csv

    if debug:
        logging.getLogger().addHandler(logging.StreamHandler(stream=sys.stdout))
        logging.getLogger().setLevel(logging.DEBUG)

    special_departments = {
        "4885": "深圳投资银行部",
        "4890": "北京投资银行部",
        "4906": "上海债券融资部",
        "4913": "北京债券融资部",
        "6139": "深圳债券融资部",
    }

    def _inner(file_path, encoding, callback):
        sync_data = []
        secondary_dept_data = {}
        with open(file_path, 'rt', encoding=encoding) as csvfile:
            for row in csv.DictReader(csvfile):
                logging.debug("%s", row)
                secondary_dept_flag, res = callback(row)
                if secondary_dept_flag:
                    logging.info('find secondary_dept data: %s', res)
                    secondary_dept_data[res['external_id']] = res
                elif res:
                    logging.info('add new instance: %s', res)
                    sync_data.append(res)
        return sync_data, secondary_dept_data

    def _user(row):
        # emp_no(uid)  emp_name(user_name)  depid  jobproperty  email  office_phone
        department_id = row['DEPID']
        insert_user_data = {
            'department': '',
            'department_id': department_id,
            'username': row['EMP_NAME'],
            'email': row['EMAIL'],
            'is_oa': True,
            'is_sync': True
        }
        user_department_ins = db_session.query(Department).filter(Department.external_id == department_id, Department.deleted == 0).first()
        if not user_department_ins:
            # 二级部门上级部门存在且为一级部门的，二级部门下用户放到一级部门下
            if department_id in need_fix_departments:
                sync_dept_data = need_fix_departments[department_id]
                parent_id = sync_dept_data['parent_id']
                parent_dept = db_session.query(Department).filter(Department.external_id == parent_id, Department.deleted == 0,
                                                                  Department.department_type == Department.HT_PRIMARY_SECTOR).first()
                if parent_dept:
                    insert_user_data.update(
                        {
                            'department': parent_dept.name,  # 部门信息更新为上级部门信息
                            'department_id': parent_id,
                            'org_department_id': department_id,  # 记录原始部门信息
                            'org_department': sync_dept_data['name'],
                            'department_ins': parent_dept
                        }
                    )
                    logging.info(
                        'replace department to parent_department, user: %s, %s, org_department_id=%s, org_department=%s, new_department_id=%s, new_department_id=%s',
                        row['EMP_NO'], row['EMP_NAME'], department_id, sync_dept_data['name'], parent_id, parent_dept.name)
            else:
                logging.info('user: %s, %s can not find department: %s', row['EMP_NO'], row['EMP_NAME'], department_id)
        else:
            insert_user_data.update(
                {
                    'department': user_department_ins.name,
                    'department_ins': user_department_ins
                }
            )
        user = User.make_user(row['EMP_NO'], row['EMP_NO'], **insert_user_data)
        user.user_data.update({'allow_login': True})
        user.user_data.pop('expired_time', None)
        flag_modified(user, 'user_data')
        db_session.commit()
        return False, user.ext_uname

    def _depart(row):
        # 机构代码的话，用dept_id就行，dep_org_no这个字段是目前可以不考虑，dep_org_no相当于是一级部门、分公司、营业部的代码 ，没有dep_org_no的这些是一级部门下面的二级部门
        # (跟用户)关联用dept_id
        # 总部：dept_type为0，supr_org_id为-1
        # 一级部门：0，dept_type为0，supr_org_id为总部对应的DEPT_ID
        # 二级部门：dept_type为1（先不管这种情况）
        # 分公司：dept_type为2，supr_org_id为总部对应的DEPT_ID
        # 营业部：dept_type为3，supr_org_id为其所属分公司对应的DEPT_ID
        # dept_id	dept_name	dept_type	dep_org_no	supr_org_id
        # 过滤掉DEPT_ID为空的部门
        # 二级部门没有所属一级部门，指定同步部分二级部门，作为一级部门处理

        try:
            department_type = int(row['DEPT_TYPE'])
        except Exception:
            logging.error('department type error: %s', row)
            return False, None

        if not row['DEPT_ID']:
            return False, None

        data = {
            'external_id': row['DEPT_ID'],
            'name': row['DEPT_NAME'],
            'parent_id': row['SUPR_ORG_ID'],
            'department_type': department_type,
            'data': {
                'is_sync': True,
                'dept_org_no': row['DEP_ORG_NO'],
            },
        }
        if department_type == Department.HT_SECONDARY_SECTOR:
            return True, data
        create_department_ins = Department.init(**data)
        return False, create_department_ins and create_department_ins.external_id

    def get_sync_count(file_path, encoding):
        with open(file_path, 'rt', encoding=encoding) as csvfile:
            return len(list(csv.DictReader(csvfile)))

    def check_sync_info_valid(file_path, db_count):
        try:
            sync_count = get_sync_count(file_path, 'utf-8')
        except UnicodeDecodeError:
            sync_count = get_sync_count(file_path, 'gbk')
        return sync_count, sync_count > db_count // 2

    logging.info('loading depart data')
    db_departments = db_session.query(Department).filter(Department.department_type.notin_([Department.HT_SECONDARY_SECTOR, Department.HT_OTHER_DEPARTMENT]),
                                                         Department.deleted == 0).all()
    sync_counts, flag = check_sync_info_valid(dept_file, len(db_departments))
    if not flag:
        logging.error('sync department lines less than expected, sync_count=%s', sync_counts)
        return

    db_users = db_session.query(User).filter(User.is_oa.is_(True), User.deleted == User.USER_STATUS_DEFAULT).all()
    sync_counts, flag = check_sync_info_valid(user_file, len(db_users))
    if not flag:
        logging.error('sync user lines less than expected, sync_count=%s', sync_counts)
        return

    try:
        sync_departments, need_fix_departments = _inner(dept_file, 'utf-8', _depart)
    except UnicodeDecodeError:
        sync_departments, need_fix_departments = _inner(dept_file, 'gbk', _depart)

    # 总部
    head_quarter = db_session.query(Department).filter(Department.parent_id == '-1', Department.department_type == Department.HT_PRIMARY_SECTOR,
                                                       Department.deleted == 0).first()
    head_quarter_id = head_quarter.external_id if head_quarter else None
    logging.info('need fix secondary departments length: %s', len(need_fix_departments))
    # 二级部门没有所属一级部门，指定同步部分二级部门，作为一级部门处理
    for dept_id, dept_name in special_departments.items():
        if dept_id in need_fix_departments and need_fix_departments[dept_id]['name'] == dept_name:
            secondary_item_data = need_fix_departments[dept_id]
            secondary_item_data['parent_id'] = head_quarter_id
            secondary_item_data['department_type'] = Department.HT_PRIMARY_SECTOR
            department_ins = Department.init(**secondary_item_data)
            if department_ins:
                logging.info('add secondary dept to primary dept, dept_id=%s, dept_name=%s', dept_id, dept_name)
                sync_departments.append(department_ins.external_id)
        else:
            logging.info('can not find secondary dept_id=%s, dept_name=%s in sync data', dept_id, dept_name)

    # 除其他及二级部门，删除未在同步数据中的部门
    delete_departments = []
    for db_department in db_departments:
        if db_department.external_id not in sync_departments:
            logging.info('delete not exist in sync departments: department_id=%s, name=%s, department_type=%s', db_department.external_id,
                         db_department.name, db_department.department_type)
            db_department.deleted = 1
            delete_departments.append(db_department.external_id)
    # 清除一级部门对应的二级部门
    secondary_db_departments = db_session.query(Department).filter(Department.parent_id.in_(delete_departments), Department.deleted == 0,
                                                                   Department.department_type == Department.HT_SECONDARY_SECTOR).all()
    for secondary_db_department in secondary_db_departments:
        logging.info('delete secondary departments: department_id=%s, name=%s, parent_id=%s', secondary_db_department.external_id,
                     secondary_db_department.name, secondary_db_department.parent_id)
        secondary_db_department.deleted = 1
    db_session.commit()

    # 创建其他部门
    department_data = {
        'is_sync': False,
        'dept_org_no': ''
    }
    Department.init('999999', "其它部门", parent_id=head_quarter_id, department_type=Department.HT_OTHER_DEPARTMENT, data=department_data)

    logging.info('loading user data')
    try:
        sync_users, _ = _inner(user_file, 'utf-8', _user)
    except UnicodeDecodeError:
        sync_users, _ = _inner(user_file, 'gbk', _user)

    # 清除未在同步数据中的oa用户
    expired_time = get_config('webif.abnormal_user_expired_time', 1209600)  # 2 week
    for db_user in db_users:
        if db_user.ext_uname not in sync_users:
            logging.info('delete not exist in sync user: ext_uname=%s', db_user.ext_uname)
            db_user.deleted = User.HT_USER_STATUS_ABNORMAL  # 标记为异常用户
            current_time = generate_timestamp()
            db_user.user_data['expired_time'] = current_time + expired_time
            flag_modified(db_user, 'user_data')
            db_user.process_time = current_time
    db_session.commit()


def get_and_load_data_file_func(domain=None, account=None, password=None, user_path=None, depart_path=None, debug=False):
    """
    下载并导入数据文件
    如果某个参数不传,将是用配置文件中的对应项: "command.get_data.*"
    """
    logging.getLogger().addHandler(logging.StreamHandler(stream=sys.stdout))
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    try:
        domain, account, password, user_path, depart_path = _combine_params(
            domain, account, password, user_path, depart_path
        )

        user_file = '/tmp/data_query_user.csv'
        depart_file = '/tmp/data_query_depart.csv'

        andu = AnduAPI(domain, account, password)
        user_file_data = andu.download_file(user_path)
        with open(user_file, 'wb') as fwriter:
            fwriter.write(user_file_data)

        depart_file_data = andu.download_file(depart_path)
        with open(depart_file, 'wb') as fwriter:
            fwriter.write(depart_file_data)

        load_data_file_func(user_file, depart_file, debug)
    except Exception as exp:
        print("success: false")
        print(f"message: {repr(exp)}")
    else:
        print("success: true")
        print(f"message: ok")


@app.task
def sync_department_user():
    get_and_load_data_file_func()
