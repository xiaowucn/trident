#!/bin/bash

run() {
  "$@"
  _exit_code=$?
  if [[ ${_exit_code} -ne 0 ]]; then
    echo "Error: exec $* with exit code ${_exit_code}"
    exit ${_exit_code}
  fi
}
run rsync -av --delete --exclude=/data --exclude=/user_proxy/static --exclude=.git  ./ ci@100.64.0.3:/data/scriber_guosen_test/code_src/trident/
run ssh ci@100.64.0.3  docker exec trident_guosen_test bash -c "./docker/deploy_upgrade.sh"

if [[ -f "/data/ci/fitout/autodoc/send_mm_msg.sh" ]]; then
  bash /data/ci/fitout/autodoc/send_mm_msg.sh http://mm.paodingai.com/hooks/xffd4wkndpnjubqd9z9puzoxaa trident \[Trident\ 国信测试环境\]\(http://100.64.0.3:21010/#/login\)后端已更新至版本\:\`${GO_REVISION_TRIDENT:0:8}\(${GO_MATERIAL_BRANCH_TRIDENT}\)\`
fi
