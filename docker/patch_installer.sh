#!/bin/bash

set -e

if [[ "$(id -u)" = '0' ]]; then
  exec gosu trident "/docker/patch_installer.sh" "$@"
  exit $?
fi

if [[ -f "/data/.env" ]]; then
  . /data/.env
fi

_trident_work_dir="/opt/trident/"
_patch_work_dir="/tmp/trident_patch/"
_patch_path="/data/patch/patch_trident_$(cat ${_trident_work_dir}.version).tgz"
_supervisor_sock="/dev/shm/supervisor.sock"

_exit() {
  _exit_code=$?
  if [[ "$_exit_code" -ne 0 ]]; then
    echo "install patch ${_patch_path} failed !!!"
  fi
  rm -rf ${_patch_work_dir}
  exit "${_exit_code}"
}

trap _exit HUP INT EXIT TERM QUIT

if [[ -f "${_patch_path}" ]]; then
  echo "patch package found, start install patch ..."
  mkdir -p "${_patch_work_dir}"
  tar xzf "${_patch_path}" -C "${_patch_work_dir}"
  chown -R $(id -u) "${_patch_work_dir}"
  cp -rf "${_patch_work_dir}"/* "${_trident_work_dir}"

  if [[ -e "${_supervisor_sock}" ]]; then
    echo "restarting services ..."
    supervisorctl restart all >/dev/null 2>&1
  fi
  echo "patch install success ..."

else
  echo "no patch package found in ${_patch_path}, do nothing ..."
fi
