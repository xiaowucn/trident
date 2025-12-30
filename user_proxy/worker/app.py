# coding: utf-8


from celery import Celery
from celery.schedules import crontab
from sqlalchemy.pool import NullPool

from user_proxy import config
from user_proxy.db import KEY_PREFIX


def get_broker_info():
    broker = config.get_config("worker.broker", "")
    if broker.startswith("redis"):
        return (
            broker,
            broker,
            {
                "priority_steps": list(range(10)),
                "visibility_timeout": 360000,
                'global_keyprefix': KEY_PREFIX
            },
            {'global_keyprefix': KEY_PREFIX},
        )
    if broker.startswith('sentinel'):
        master_name = config.get_config("webif.session.sentinel.master_name")
        return (
            broker,
            config.get_config("worker.backend"),
            {"priority_steps": list(range(10)), "visibility_timeout": 360000, 'master_name': master_name, 'global_keyprefix': KEY_PREFIX},
            {'master_name': master_name, 'global_keyprefix': KEY_PREFIX},
        )
    if broker.startswith("sqla"):
        backend = "db+postgresql+psycopg2" + broker.lstrip("sqla+postgresql")
        return broker, backend, {'poolclass': NullPool}, {}
    return broker, broker, {}, {}


broker_url, backend_url, broker_option, backend_option = get_broker_info()

app = Celery(
    config.get_config("worker.app_name"),
    broker=broker_url,
    include=[
        "user_proxy.worker.kysec",
        'user_proxy.worker.ctsec',
        'user_proxy.worker.zts',
        'user_proxy.worker.cgs',
        'user_proxy.worker.cjsc',
        'user_proxy.worker.cicc',
        'user_proxy.worker.swhysc',
        'user_proxy.worker.xyzq',
        'user_proxy.worker.htamc',
        'user_proxy.worker.stocke',
        'user_proxy.worker.chasing',
        'user_proxy.worker.cmfchina',
        "user_proxy.worker.ht",
    ],
)

default_queue = {'queue': config.get_config("worker.default_queue", "celery")}

app.conf.update(
    worker_pool_restarts=True,
    worker_prefetch_multiplier=1,
    broker_transport_options=broker_option,
    backend_option=backend_option,
    worker_max_tasks_per_child=100,
    task_routes={
        'user_proxy.worker.kysec.*': default_queue,
        'user_proxy.worker.ctsec.*': default_queue,
        'user_proxy.worker.zts.*': default_queue,
        'user_proxy.worker.cgs.*': default_queue,
        'user_proxy.worker.cjsc.*': default_queue,
        'user_proxy.worker.cicc.*': default_queue,
        'user_proxy.worker.swhysc.*': default_queue,
        'user_proxy.worker.xyzq.*': default_queue,
        'user_proxy.worker.htamc.*': default_queue,
        'user_proxy.worker.stocke.*': default_queue,
        'user_proxy.worker.chasing.*': default_queue,
        'user_proxy.worker.cmfchina.*': default_queue,
        'user_proxy.worker.ht.*': default_queue,
    },
    enable_utc=False,
    timezone="Asia/Shanghai",
)
if backend_url and backend_option:
    app.conf.update(result_backend_transport_options=backend_option)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    if not config.get_config('worker.enable'):
        return
    config_sys = config.get_config('sys')
    if config_sys == 'kysec':
        from user_proxy.worker.kysec import sync_user_data_from_webserver, sync_user_data_from_customer_db

        period_config = config.get_config('worker.period_tasks.sync_user_info_task', {'hour': '0', 'minute': '0'})
        if config.get_config('kysec.enable'):
            sender.add_periodic_task(
                crontab(**period_config),
                sync_user_data_from_customer_db.s(),
            )
        else:
            sender.add_periodic_task(
                crontab(**period_config),
                sync_user_data_from_webserver.s(),
            )
    elif config_sys == 'ctsec':
        from user_proxy.worker.ctsec import sync_department

        period_config = config.get_config('worker.period_tasks.sync_department', {'hour': '0', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            sync_department.s(),
        )
    elif config_sys == 'zts':
        from user_proxy.worker.zts import sync_user, sync_group

        period_config = config.get_config('worker.period_tasks.sync_group', {'hour': '0', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            sync_group.s(),
        )
        period_config = config.get_config('worker.period_tasks.sync_user', {'hour': '0', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            sync_user.s(),
        )
    elif config_sys == 'cgs':
        from user_proxy.worker.cgs import sync_user, sync_group

        period_config = config.get_config('worker.period_tasks.sync_group', {'hour': '0', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            sync_group.s(),
        )
        period_config = config.get_config('worker.period_tasks.sync_user', {'hour': '0', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            sync_user.s(),
        )
    elif config_sys == 'cjsc':
        from user_proxy.worker.cjsc import sync_dept_user_from_webservice

        period_config = config.get_config('worker.period_tasks.sync_dept_user_info_task', {'hour': '0', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            sync_dept_user_from_webservice.s(),
        )
    elif config_sys == 'cicc':
        from user_proxy.worker.cicc import send_dashboard_data, sync_user_info

        period_config = config.get_config('worker.period_tasks.send_dashboard_data', {'hour': '23', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            send_dashboard_data.s(),
        )
        period_config = config.get_config('worker.period_tasks.sync_user_info', {'hour': '0', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            sync_user_info.s(),
        )
    elif config_sys == 'swhysc':
        from user_proxy.worker.swhysc import sync_user

        period_config = config.get_config('worker.period_tasks.sync_user', {'hour': '0', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            sync_user.s(),
        )
    elif config_sys == 'xyzq':
        from user_proxy.worker.xyzq import sync_user

        period_config = config.get_config('worker.period_tasks.sync_user', {'hour': '1', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            sync_user.s(),
        )
    elif config_sys == 'htamc':
        from user_proxy.worker.htamc import sync_dubbo_users

        period_config = config.get_config('worker.period_tasks.sync_user', {'hour': '2', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            sync_dubbo_users.s(),
        )
    elif config_sys == 'stocke':
        from user_proxy.worker.stocke import sync_user_data_from_customer_db

        period_config = config.get_config('worker.period_tasks.sync_user', {'hour': '2', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            sync_user_data_from_customer_db.s(),
        )
    elif config_sys == 'chasing':
        from user_proxy.worker.chasing import sync_user

        period_config = config.get_config('worker.period_tasks.sync_user', {'hour': '2', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            sync_user.s(),
        )
    elif config_sys == 'cmfchina':
        from user_proxy.worker.cmfchina import sync_user

        period_config = config.get_config('worker.period_tasks.sync_user', {'hour': '2', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            sync_user.s(),
        )

    elif config_sys == 'ht':
        from user_proxy.worker.ht import sync_department_user

        period_config = config.get_config('worker.period_tasks.sync_department_user', {'hour': '0', 'minute': '0'})
        sender.add_periodic_task(
            crontab(**period_config),
            sync_department_user.s(),
        )
