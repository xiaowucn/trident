# CYC: skip-file
import os
import sys

from invoke import Collection

if os.getenv("PSYCOPG2_GAUSS", "").lower() == "true":
    sys.path.insert(0, "/usr/lib/paoding/dist-packages")

from user_proxy import config

import user_proxy.devtools.task_web as web
import user_proxy.devtools.task_kysec as kysec
import user_proxy.devtools.task_db as db
import user_proxy.devtools.task_cicc as cicc
import user_proxy.devtools.task_icbcsz as icbcsz


namespace = Collection()
namespace.configure({
    'project_root': config.project_root
})


namespace.add_collection(Collection.from_module(web, name='web'))
namespace.add_collection(Collection.from_module(kysec, name='kysec'))
namespace.add_collection(Collection.from_module(cicc, name='cicc'))
namespace.add_collection(Collection.from_module(db, name='db'))
namespace.add_collection(Collection.from_module(icbcsz, name='icbcsz'))
