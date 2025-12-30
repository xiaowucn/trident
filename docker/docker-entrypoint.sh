#!/bin/bash

set -e

WORK_DIR='/opt/trident'
cd ${WORK_DIR}

if [[ "$(id -u)" == '0' ]] && [[ "${SKIP_NON_ROOT}" != "true" ]]; then
  if [[ -n "${HOST_USER_ID}" ]]; then
    USER_ID=${HOST_USER_ID:=1000}
    GROUP_ID=${HOST_GROUP_ID:=1000}
    if [[ $(id -u trident 2>/dev/null) != "${USER_ID}" ]]; then
      userdel -r -f trident || true
      groupadd -g "${GROUP_ID}" trident
      useradd -r -m -u "${USER_ID}" -g "${GROUP_ID}" trident
    fi
  fi
  find /data -maxdepth 1 -type d \! -user trident -exec chown -R trident:trident '{}' +
  chown trident /dev/fd/1 /dev/fd/2
  exec gosu trident "/docker/docker-entrypoint.sh" "$@"
  exit 0
fi

mkdir -p /data/logs /dev/shm/etc/supervisor/conf.d/ /dev/shm/etc/nginx/conf.d/

if [[ ! ("${ENABLE_STDOUT_LOG}" == "true" || (-n "${KUBERNETES_SERVICE_HOST}" && "${DISABLE_K8S_LOG}" != "true")) ]]; then
  exec 1>>/data/logs/init.log 2>&1
fi

install_patch() {
  if [[ -f "/docker/patch_installer.sh" ]]; then
    /docker/patch_installer.sh
  fi
}

if [[ "${PSYCOPG2_GAUSS,,}" == "true" ]]; then
  export PYTHONPATH=/usr/lib/paoding/dist-packages/:${PYTHONPATH}
fi

install_patch

get_config() {
  cd ${WORK_DIR} >/dev/null 2>&1
  RESULT=$(python3 -c "from user_proxy.config import get_config; print(get_config('$1') or \"\")" 2>/dev/null)
  cd - >/dev/null 2>&1
  echo "${RESULT}"
}

if [[ ${MODE} != "API" ]]; then
  inv db.upgrade
fi

if [[ "$ENV" == 'gjzq' ]] && [[ -d "/tridentfront/webif/" ]]; then
  rm -rf /tridentfront/webif/*
  cp -rp /opt/trident/user_proxy/static/static/* /tridentfront/webif/
  echo "front mapping success"
fi

PROXY_SEND_TIMEOUT=$(get_config "webif.proxy_send_timeout")
export PROXY_SEND_TIMEOUT=${PROXY_SEND_TIMEOUT:-600}

MAX_BODY_SIZE=$(get_config 'webif.max_buffer_size')
export MAX_BODY_SIZE=${MAX_BODY_SIZE:-209715200}

ENABLE_CRONTAB=$(get_config "worker.enable")
export ENABLE_CRONTAB

jinja2 /docker/nginx/nginx.j2 -o /dev/shm/etc/nginx/conf.d/trident.conf
jinja2 /docker/supervisor/conf.d/trident.j2 -o /etc/supervisor/conf.d/trident.conf

exec supervisord -n -c /etc/supervisor/supervisord.conf
