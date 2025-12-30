#!/usr/bin/env bash
# 注意：使用该脚本需要将compose文件命名为 docker-compose.yaml ， 并将要自动更新的镜像写入同目录的 .env 文件中，文件内容如下：
# TRIDENT_IMAGE_VERSION=registry.cheftin.cn/p/autodoc-overall-fullgoal:0.0.23
# 在 docker-compose.yaml 文件中使用 $TRIDENT_IMAGE_VERSION 引用以上变量
set -e

_deploy_user=
_deploy_server=
_deploy_path=
_mm_channel=
_mm_message=
_container_name=
_env_name="TRIDENT_IMAGE_VERSION"
registry_url=${REGISTRY_URL:-"registry.cheftin.cn/p"}

function run() {
    "$@"
    _exit_code=$?
    if [[ ${_exit_code} -ne 0 ]]; then
        echo "Error: exec $* with exit code ${_exit_code}"
        exit ${_exit_code}
    fi
}

function prompt() {
  case ${1} in
  "-s" | "--success")
    echo -e "\033[1;32m""${*/-s/}""\033[0m"
    ;; # Print success message
  "-e" | "--error")
    echo -e "\033[1;31m${*/-e/}\033[0m"
    ;; # Print error message
  "-w" | "--warning")
    echo -e "\033[1;33m${*/-w/}\033[0m"
    ;; # Print warning message
  "-i" | "--info")
    echo -e "\033[1;36m${*/-i/}\033[0m"
    ;; # Print info message
  *)
    echo -e "$@"
    ;;
  esac
}

function print_help() {
  printf '%s\n' "The make_image_package.sh script's help msg"
  printf 'Usage: %s -u <username> -s <server_ip> -p <docker-compose path> -c <mm_channel> -m <message> [-h|--help] \n' "$0"
  printf '\t%s\n' "-u, --user: deploy user (no default) (- requested -)"
  printf '\t%s\n' "-s, --server: deploy server address (- requested -)"
  printf '\t%s\n' "-p, --path: path of deploy docker-compose.yml file's directory (no default) (- requested -)"
  printf '\t%s\n' "-t, --container: container name (no default)"
  printf '\t%s\n' "-r, --registry: registry url of docker image (default: registry.cheftin.cn/p)"
  printf '\t%s\n' "-c, --channel: channel of mm (no default)"
  printf '\t%s\n' "-m, --message: message to mm (no default)"
  printf '\t%s\n' "-e, --env: env_name in file .env (default: TRIDENT_IMAGE_VERSION)"
  printf '\t%s\n' "-h, --help: prints help"
}

# to parsing of the command-line
function parse_commandline() {
  _positionals_count=0
  while test $# -gt 0; do
    _key="$1"
    case "$_key" in
    -u | --user)
      test $# -lt 2 && prompt -e "Missing value for the optional argument '$_key'." && exit 1
      _deploy_user="$2"
      shift
      ;;
    -s | --server)
      test $# -lt 2 && prompt -e "Missing value for the optional argument '$_key'." && exit 1
      _deploy_server="$2"
      shift
      ;;
    -p | --path)
      test $# -lt 2 && prompt -e "Missing value for the optional argument '$_key'." && exit 1
      _deploy_path="$2"
      shift
      ;;
    -r | --registry)
      test $# -lt 2 && prompt -e "Missing value for the optional argument '$_key'." && exit 1
      registry_url="$2"
      shift
      ;;
    -c | --channel)
      test $# -lt 2 && prompt -e "Missing value for the optional argument '$_key'." && exit 1
      _mm_channel="$2"
      shift
      ;;
    -m | --message)
      test $# -lt 2 && prompt -e "Missing value for the optional argument '$_key'." && exit 1
      _mm_message="$2"
      shift
      ;;
    -t | --container)
      test $# -lt 2 && prompt -e "Missing value for the optional argument '$_key'." && exit 1
      _container_name="$2"
      shift
      ;;
    -e | --env)
      test $# -lt 2 && prompt -e "Missing value for the optional argument '$_key'." && exit 1
      _env_name="$2"
      shift
      ;;
    -h | --help)
      print_help
      exit 0
      ;;
    *)
      _last_positional="$1"
      _positionals+=("$_last_positional")
      _positionals_count=$((_positionals_count + 1))
      ;;
    esac
    shift
  done
}

# 定义部署
function deploy() {
    local deplopy_path="${1}"
    local registry_url="${2:-"registry.cheftin.cn/p"}"
    local image_version="${3}"
    local env_name="${4}"
    # pull
    prompt -i ">>> INFO: Start pull ${registry_url}/${image_version}"
    docker pull "${registry_url}"/"${image_version}"

    # sed
    prompt -i ">>> INFO: Start modify ${deplopy_path}"
    sed -ir "s#${env_name}=.*#${env_name}=${registry_url}/${image_version}#" "${deplopy_path}"/.env

    # up
    prompt -i ">>> INFO: Start exec docker-compose up -d"
    docker-compose -f "${deplopy_path}"/docker-compose.yaml up -d
}

# 定义监控容器健康状态的函数（在远程服务器上执行）
function monitor_container_health_remote() {
    local container_name="${1}"
    local timeout="${2:-300}"  # 默认超时 300 秒（5分钟）
    local interval="${3:-5}"   # 默认检查间隔 5 秒

    prompt -i ">>> INFO: Starting to monit health_status for ${container_name} ..."

    start_time=$(date +%s)
    end_time=$((start_time + timeout))

    while [ "$(date +%s)" -lt "$end_time" ]; do
        health_status=$(docker inspect --format='{{.State.Health.Status}}' "${container_name}" 2>/dev/null)

        if [ $? -ne 0 ]; then
            prompt -e ">>> ERROR: Getting container ${container_name} status failed，please check container is exist" >&2
            exit 1
        fi

        case "$health_status" in
            "healthy")
                prompt -s ">>> INFO: $(date '+%Y-%m-%d %H:%M:%S') - ✅ Container ${container_name} has been healthy."
                exit 0
                ;;
            "unhealthy")
                prompt -w ">>> WARNING: $(date '+%Y-%m-%d %H:%M:%S') - ❌ Container ${container_name} status is unhealthy, please check." >&2
                ;;
            "starting")
                prompt -i ">>> INFO: $(date '+%Y-%m-%d %H:%M:%S') - ⏳ Container ${container_name} is starting..."
                ;;
            *)
                echo "$(date '+%Y-%m-%d %H:%M:%S') - ℹ️ Container ${container_name} status: ${health_status}"
                ;;
        esac

        sleep "$interval"
    done

    prompt -w ">>> WARNING: ⏱️ Monitor timeout：Container ${container_name} does not healthy in ${timeout}s" >&2
    exit 1
}

send_mm_msg() {
local MM_URL=$1
local MM_CHANNEL=$2
local MM_TEXT=$3

run curl "${MM_URL}" \
    -H 'Content-Type: application/json; charset=utf-8' \
    -d @- << EOF -o /dev/null 2>/dev/null
{
    "text": "${MM_TEXT}",
    "channel": "${MM_CHANNEL}",
    "icon_url": "http://res.cloudinary.com/kdr2/image/upload/c_crop,g_faces,h_240,w_240/v1454772214/misc/c3p0-001.jpg",
    "username": "CI"
}
EOF
}

parse_commandline "$@"

if [[ -n ${IMAGE_NAME} ]]; then
  # env
  image_version="${IMAGE_NAME}:0.0.${GO_PIPELINE_COUNTER}"

  if [[ ${_deploy_path} == */ ]]; then
    _deploy_path="${_deploy_path/$\//}"
  fi

  if [[ -z "${_deploy_user}" || -z "${_deploy_server}" || -z "${_deploy_path}" ]]; then
    prompt -e ">>> ERROR: Required parameter missing, please check."
    exit 1
  fi

  # deploy and monitor
  if [[ -z "${_container_name}" ]]; then
    run ssh "${_deploy_user}@${_deploy_server}" \
          "$(declare -f prompt); \
           $(declare -f deploy); \
           deploy '${_deploy_path}' '${registry_url}' '${image_version}' '${_env_name}'"
  else
    run ssh "${_deploy_user}@${_deploy_server}" \
        "$(declare -f prompt); \
         $(declare -f deploy); \
         $(declare -f monitor_container_health_remote); \
         deploy '${_deploy_path}' '${registry_url}' '${image_version}' '${_env_name}'; \
         monitor_container_health_remote '${_container_name}'"
  fi

  # send_msg
  if [[ -n "${_mm_channel}" && -n "${_mm_message}" ]]; then
    run prompt -i ">>> INFO: Start send_mm_msg"
    run send_mm_msg http://mm.paodingai.com/hooks/xffd4wkndpnjubqd9z9puzoxaa "${_mm_channel}" "${_mm_message}"
    run prompt -s ">>> INFO: Send_mm_msg success"
  else
    run prompt -w ">>> WARNING：no channel or message,skip send to mm"
  fi
else
  run prompt -e ">>> ERROR: \$IMAGE_NAME is null,please check!!"
  exit 1
fi
