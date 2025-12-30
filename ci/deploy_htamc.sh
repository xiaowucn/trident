#!/usr/bin/env bash

run() {
  "$@"
  _exit_code=$?
  if [ ${_exit_code} -ne 0 ]; then
    echo "Error: exec "$@" with exit code ${_exit_code}"
    exit ${_exit_code}
  fi
}

#C124
run rsync -av --delete --exclude=.git --exclude=/user_proxy/static/ ./ ci@100.64.0.12:/data/htamc_dev/trident/code/

run ssh ci@100.64.0.12 "docker exec -i htamc_dev_trident bash -c './docker/deploy_upgrade.sh'"

if [[ -f "/data/ci/fitout/autodoc/send_mm_msg.sh" ]]; then
  bash /data/ci/fitout/autodoc/send_mm_msg.sh http://mm.paodingai.com/hooks/xffd4wkndpnjubqd9z9puzoxaa trident "[Trident-华泰资管-后端-测试环境](http://100.64.0.12:38001)已更新至版本:\`${GO_REVISION_TRIDENT:0:8}(${GO_MATERIAL_BRANCH_TRIDENT})\`"
fi
