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
run rsync -av --delete --exclude=/data --exclude=/user_proxy/static --exclude=.git  ./ /data/trident_ht/trident/
run rsync -av --delete ../front_trident/dist_ht/ /data/trident_ht/trident_fronts/dist_ht/
run docker exec ht_trident bash -c "./docker/deploy_upgrade.sh"

cd ${WORK_DIR}
if [[ -f "/data/ci/fitout/autodoc/send_mm_msg.sh" ]]; then
  bash /data/ci/fitout/autodoc/send_mm_msg.sh http://mm.paodingai.com/hooks/xffd4wkndpnjubqd9z9puzoxaa trident \[Trident\ ht测试环境\]\(http://100.64.0.9:55832\)后端已更新至版本\:\`${GO_REVISION_TRIDENT:0:8}\(${GO_MATERIAL_BRANCH_TRIDENT}\)\`
fi