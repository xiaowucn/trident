#!/bin/bash

run () {
    "$@"
    _exit_code=$?
    if [[ ${_exit_code} -ne 0 ]]; then
        echo "Error: exec "$@" with exit code ${_exit_code}"
        exit ${_exit_code}
    fi
}

WORK_DIR=$(pwd)
#run rsync -av --exclude=/data --exclude=.git  ./ /data/trident_general/trident/
#run /data/trident_general/venv/bin/pip install --upgrade -r /data/trident_general/trident/requirements.txt
run /data/trident_general/venv/bin/alembic -c migrations/alembic.ini -x dburl=postgresql+psycopg2://postgres:I7FQ9T0S75@127.0.0.1:6432/user_proxy7 upgrade head
run sudo supervisorctl restart trident-szse-test-web

cd ${WORK_DIR}
if [[ -f "/data/ci/fitout/autodoc/send_mm_msg.sh" ]]; then
  bash /data/ci/fitout/autodoc/send_mm_msg.sh http://mm.paodingai.com/hooks/xffd4wkndpnjubqd9z9puzoxaa trident \[Trident\ szse测试环境\]\(http://bj.cheftin.com:55816\)后端已更新至版本\:\`${GO_REVISION_TRIDENT:0:8}\(${GO_MATERIAL_BRANCH_TRIDENT}\)\`
fi
