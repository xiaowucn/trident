#!/bin/bash

run() {
  "$@"
  _exit_code=$?
  if [[ ${_exit_code} -ne 0 ]]; then
    echo "Error: exec "$@" with exit code ${_exit_code}"
    exit ${_exit_code}
  fi
}

# env
TRIDENT_VERSION="trident_icbccs:0.0.${GO_PIPELINE_COUNTER}"

# pull
run docker pull registry.cheftin.cn/p/${TRIDENT_VERSION}

# sed
run sed -i -r "s@trident_icbccs:0.0..{1,4}@${TRIDENT_VERSION}@" /data2/trident_icbccs_demo/docker-compose.yml

# up
run docker-compose -f /data2/trident_icbccs_demo/docker-compose.yml up -d

if [[ -f "/data/ci/fitout/autodoc/send_mm_msg.sh" ]]; then
  bash /data/ci/fitout/autodoc/send_mm_msg.sh http://mm.paodingai.com/hooks/xffd4wkndpnjubqd9z9puzoxaa trident \[Trident工银瑞信测试环境\]\(http://100.64.0.10:30\)后端已更新至版本\:\`${GO_REVISION_TRIDENT:0:8}\(${GO_MATERIAL_BRANCH_TRIDENT}\)\`
fi
