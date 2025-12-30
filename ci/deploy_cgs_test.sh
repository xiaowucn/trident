#!/bin/bash

run() {
  "$@"
  _exit_code=$?
  if [[ ${_exit_code} -ne 0 ]]; then
    echo "Error: exec $* with exit code ${_exit_code}"
    exit ${_exit_code}
  fi
}

run docker exec cgs_trident bash -c "./docker/deploy_upgrade.sh"

if [[ -f "/data/ci/fitout/autodoc/send_mm_msg.sh" ]]; then
  bash /data/ci/fitout/autodoc/send_mm_msg.sh http://mm.paodingai.com/hooks/xffd4wkndpnjubqd9z9puzoxaa trident \[Trident\ cgs银河测试环境\]\(http://100.64.0.9:55850\)后端已更新至版本\:\`${GO_REVISION_TRIDENT:0:8}\(${GO_MATERIAL_BRANCH_TRIDENT}\)\`
fi
