import logging
from typing import Dict

import requests
from sqlalchemy.orm.attributes import flag_modified

from user_proxy import config
from user_proxy.db import db_session
from user_proxy.models.user import Department
from user_proxy.worker.app import app

DEPARTMENT_REQUEST_SERVER = config.get_config('ctsec.department.server')
DEPARTMENT_REQUEST_URI = config.get_config('ctsec.department.uri')


@app.task
def sync_department():
    if not (DEPARTMENT_REQUEST_URI and DEPARTMENT_REQUEST_SERVER):
        return
    response = requests.get(
        f'{DEPARTMENT_REQUEST_SERVER}/{DEPARTMENT_REQUEST_URI}',
        headers=config.get_config('ctsec.department.headers', {}),
    )
    departments = db_session.query(Department).filter(Department.external_id.isnot(None)).all()
    exists_departments: Dict[str, Department] = {depart.external_id: depart for depart in departments}

    departments = response.json()['data']
    department: dict
    for department in departments:
        model = exists_departments.pop(
            str(department['orgId']),
            Department(external_id=department['orgId'])
        )
        for attr, key in [
            ('parent_id', 'parentId'),
            ('name', 'title'),
        ]:
            setattr(model, attr, department[key])
        model.data = model.data or {}
        model.data.update(department)
        flag_modified(model, 'data')
        db_session.add(model)
        logging.info('add new department orgId=%s, title=%s', model.external_id, model.name)
    for model in exists_departments.values():
        db_session.delete(model)
        logging.info('delete invalid department orgId=%s, title=%s', model.external_id, model.name)
    db_session.commit()


if __name__ == '__main__':
    sync_department()
