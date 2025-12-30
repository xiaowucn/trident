#!/bin/bash


run() {
  "$@"
  _exit_code=$?
  if [ ${_exit_code} -ne 0 ]; then
#     if [ -f "/data/ci/fitout/common/get_commit_users.py" ]; then
#       MENTION_USERS=$(python3 /data/ci/fitout/common/get_commit_users.py)
#     fi
#
#     if [ -f "/data/ci/fitout/autodoc/send_mm_msg.sh" ]; then
#       GO_LOG_URL="https://gocd.paodingai.com/go/tab/build/detail/Trident-backend-Dev/${GO_PIPELINE_COUNTER}/deploy_htamc/${GO_STAGE_COUNTER}/deploy"
#       bash /data/ci/fitout/autodoc/send_mm_msg.sh http://mm.paodingai.com/hooks/xffd4wkndpnjubqd9z9puzoxaa trident "| 代码提交人 | 错误信息 | 构建日志地址 |\n| --- | --- | --- |\n| :facebug: *${MENTION_USERS}* | :x: **Trident Dev Test Error** | :point_right: [*click the jump*](${GO_LOG_URL}) |"
#     fi
    echo "Error: exec "$@" with exit code ${_exit_code}"
    exit ${_exit_code}
  fi
}

run rsync -av --delete --exclude=/data --exclude=/user_proxy/static --exclude=.git  ./ /data/trident_general/trident/
run docker exec general_trident bash -c "./docker/deploy_upgrade.sh"


if [[ -f "/data/ci/fitout/autodoc/send_mm_msg.sh" ]]; then
  bash /data/ci/fitout/autodoc/send_mm_msg.sh http://mm.paodingai.com/hooks/xffd4wkndpnjubqd9z9puzoxaa trident \[Trident通用测试环境\]\(http://100.64.0.9:55820\)后端已更新至版本\:\`${GO_REVISION_TRIDENT:0:8}\(${GO_MATERIAL_BRANCH_TRIDENT}\)\`
fi