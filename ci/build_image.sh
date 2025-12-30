#!/usr/bin/env bash

set -e
# 1. 必须开启 BuildKit (为了支持 --mount 和 --platform)
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
  # 5. 构建命令：使用正确的 BUILD_PLATFORM 变量
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

# 【核心修改 1】将默认架构从 linux/amd64 改为 linux/arm64
BUILD_PLATFORM=${BUILD_PLATFORM:-"linux/arm64"}

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
    # 2. 准备 Dockerfile
    # 注意：这里需要先准备好文件，才能进行后面的 sed 替换
    ln -sf docker/Dockerfile ./Dockerfile
    ln -snf docker/dockerignore ./.dockerignore
    
    # 原始逻辑：删除 default-jre
    sed -i '/default-jre/d' Dockerfile
    ;;
esac

# 【核心修改 2】强制替换 Dockerfile 中的仓库地址 (这步非常关键)
# 确保 Dockerfile 里的 FROM 能用到你在 GoCD 里配置的 harbor.wujiaxing.top
if [[ -n "${REGISTRY_URL}" ]]; then
    echo "Force updating registry url in Dockerfile to: ${REGISTRY_URL}"
    sed -i "s|registry.cheftin.cn/hub|${REGISTRY_URL}|g" Dockerfile
    sed -i "s|harbor.wujiaxing.top/library|${REGISTRY_URL}|g" Dockerfile
fi

# 确保软链存在 (防止 case 分支没走到的情况)
if [ ! -f Dockerfile ]; then
    ln -sf docker/Dockerfile ./Dockerfile
    ln -snf docker/dockerignore ./.dockerignore
fi

echo -n "${ENV:=docker}_${IMAGE_VERSION}" >.version

update_front
build_image
if check_image; then
  push_registry
fi
