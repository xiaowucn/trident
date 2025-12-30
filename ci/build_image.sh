#!/usr/bin/env bash

set -e
export DOCKER_BUILDKIT=1

check_image() {
  echo 'check image start ... '
  if [[ -f "/data/ci/fitout/common/print_image_not_clean_file.sh" ]]; then
    /data/ci/fitout/common/print_image_not_clean_file.sh --image "${IMAGE_NAME}:${IMAGE_VERSION}"
    if [[ $? -ne 0 ]]; then
      echo 'check image end, but have some problems ... '
      exit 1
    fi
  fi
  echo 'check image end, no problem ... '
  return 0
}

build_image() {
  if ! docker build --pull --progress=plain --platform="${BUILD_PLATFORM}" --squash --no-cache \
      --build-arg env="${ENV:=docker}" --tag="${IMAGE_NAME}:${IMAGE_VERSION}" .; then
    echo 'build images error'
    exit 1
  fi
}

update_front() {
  rm -rf user_proxy/static
  mkdir -p user_proxy/static

  if ls ../dist*/dist*/ 2>&1 1>/dev/null; then
    cp -rf ../dist*/dist*/* user_proxy/static/
  fi

  if ls ../front_trident/dist*/ 2>&1 1>/dev/null; then
    cp -rf ../front_trident/dist*/* user_proxy/static/
  fi
}

push_registry() {
  echo 'push registry'
  if [[ -n "${REGISTRY_URL}" ]]; then
    docker rmi "${REGISTRY_URL}/${IMAGE_NAME}":0.0.$((GO_PIPELINE_COUNTER - 2)) || true
    docker tag "${IMAGE_NAME}:${IMAGE_VERSION}" "${REGISTRY_URL}/${IMAGE_NAME}:${IMAGE_VERSION}"
    docker push "${REGISTRY_URL}/${IMAGE_NAME}:${IMAGE_VERSION}"
  fi
}

BUILD_PLATFORM=${BUILD_PLATFORM:-"linux/amd64"}

IMAGE_NAME=${IMAGE_NAME:-'trident'}
IMAGE_VERSION="dev"
if [[ -n "${GO_PIPELINE_COUNTER}" ]]; then
  IMAGE_VERSION=0.0.${GO_PIPELINE_COUNTER}
  docker rmi "${IMAGE_NAME}":0.0.$((GO_PIPELINE_COUNTER - 2)) || true
fi

case "$ENV" in
  ctsec|gtja|gtja_llm|ht)
    ;;
  *)
    sed -i '/default-jre/d' docker/Dockerfile
    ;;
esac

ln -sf docker/Dockerfile ./Dockerfile
ln -snf docker/dockerignore ./.dockerignore

echo -n "${ENV:=docker}_${IMAGE_VERSION}" >.version

update_front
build_image
if check_image; then
  push_registry
fi
