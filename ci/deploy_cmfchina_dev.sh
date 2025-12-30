#!/usr/bin/env bash


run() {
  "$@"
  _exit_code=$?
  if [ ${_exit_code} -ne 0 ]; then
    if [ -f "/data/ci/fitout/common/get_commit_users.py" ]; then
      MENTION_USERS=$(python3 /data/ci/fitout/common/get_commit_users.py)
    fi

    echo "Error: exec "$@" with exit code ${_exit_code}"
    exit ${_exit_code}
  fi
}

#C122
run rsync -av --delete --exclude=.git --exclude=/user_proxy/static/ ./ ci@100.64.0.11:/data/trident_cmfchina_dev/code_src/trident

run ssh ci@100.64.0.11 "docker exec -i trident_cmfchina_dev_web bash -c './docker/deploy_upgrade.sh'"

if [[ -f "/data/ci/fitout/autodoc/send_mm_msg.sh" ]]; then
  bash /data/ci/fitout/autodoc/send_mm_msg.sh http://mm.paodingai.com/hooks/xffd4wkndpnjubqd9z9puzoxaa trident "[Trident-招商基金-后端-测试环境](http://100.64.0.11:22102)已更新至版本:\`${GO_REVISION_TRIDENT:0:8}(${GO_MATERIAL_BRANCH_TRIDENT})\`"
fi

