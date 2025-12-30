#!/usr/bin/env bash

run() {
  "$@"
  _exit_code=$?
  if [ ${_exit_code} -ne 0 ]; then
    echo "Error: exec "$@" with exit code ${_exit_code}"
    exit ${_exit_code}
  fi
}

#C13
run rsync -av --delete --exclude=.git --exclude=/user_proxy/static/ ./ ci@100.64.0.13:/data/autodoc_lhratings_test/trident_code/trident

run ssh ci@100.64.0.13 "docker exec -i lhratings_test_trident bash -c './docker/deploy_upgrade.sh'"

if [[ -f "/data/ci/fitout/autodoc/send_mm_msg.sh" ]]; then
  bash /data/ci/fitout/autodoc/send_mm_msg.sh http://mm.paodingai.com/hooks/xffd4wkndpnjubqd9z9puzoxaa trident "[Trident-联合资信-后端-测试环境](http://100.64.0.13:25700)已更新至版本:\`${GO_REVISION_TRIDENT:0:8}(${GO_MATERIAL_BRANCH_TRIDENT})\`"
fi
