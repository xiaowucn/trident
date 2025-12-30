#!/bin/bash

run() {
  "$@"
  _exit_code=$?
  if [[ ${_exit_code} -ne 0 ]]; then
    echo "Error: exec $* with exit code ${_exit_code}"
    exit ${_exit_code}
  fi
}

# env
TRIDENT_VERSION="trident_nesc:0.0.${GO_PIPELINE_LABEL}"

# pull
run ssh ci@100.64.0.13 "docker pull registry.cheftin.cn/p/${TRIDENT_VERSION}"

# sed
run ssh ci@100.64.0.13 "sed -i -r \"s@trident_nesc:0.0..{1,4}@${TRIDENT_VERSION}@\" /data/trident_nesc_test/docker-compose.yml"

# up
run ssh ci@100.64.0.13 "docker-compose -f /data/trident_nesc_test/docker-compose.yml up -d"

if [[ -f "/data2/ci/fitout/autodoc/send_mm_msg.sh" ]]; then
  bash /data2/ci/fitout/autodoc/send_mm_msg.sh http://mm.paodingai.com/hooks/xffd4wkndpnjubqd9z9puzoxaa trident \[Trident东北证券测试环境\]\(http://100.64.0.13:23212/#/login\)前后端已更新至版本\:\`"${GO_REVISION_TRIDENT:0:8}"\("${GO_MATERIAL_BRANCH_TRIDENT}"\)\`
fi
