#!/usr/bin/env bash

set -e

# 【关键修改 1】必须开启 BuildKit，否则 --mount 语法会报错
export DOCKER_BUILDKIT=1

IMAGE_VERSION="latest"
IMAGE_NAME="trident-py312-runtime-arm64"

# 准备 Dockerfile
ln -sf docker/runtime/Dockerfile ./
ln -sf docker/runtime/dockerignore .dockerignore

# 【关键修改 2】替换仓库地址
if [ -n "${REGISTRY_URL}" ]; then
    echo "Force updating registry url to: ${REGISTRY_URL}"
    sed -i "s|registry.cheftin.cn/hub|${REGISTRY_URL}|g" Dockerfile
    sed -i "s|harbor.wujiaxing.top/library|${REGISTRY_URL}|g" Dockerfile
fi

# 【关键修改 3】删除 --platform 参数
# 即使开启了 BuildKit，在单机 build 模式下 $TARGETPLATFORM 变量有时也为空，会导致报错。
# 既然你是本机构建（arm64），直接删掉这个参数最稳妥。
echo "Removing --platform flag from Dockerfile..."
sed -i 's/--platform=$TARGETPLATFORM //g' Dockerfile

build_image() {
  echo "Start building image with BuildKit..."
  # 恢复了 --progress=plain 以便查看详细日志
  if ! docker build --pull --progress=plain --squash --no-cache --tag="${IMAGE_NAME}:${IMAGE_VERSION}" .; then
    echo 'build images error'
    exit 1
  fi
}

push_registry() {
  if [ -n "${REGISTRY_URL}" ]; then
    docker rmi "${REGISTRY_URL}/${IMAGE_NAME}":0.0.$((GO_PIPELINE_COUNTER - 2)) || true
    docker tag "${IMAGE_NAME}:${IMAGE_VERSION}" "${REGISTRY_URL}/${IMAGE_NAME}:${IMAGE_VERSION}"
    docker push "${REGISTRY_URL}/${IMAGE_NAME}:${IMAGE_VERSION}"
  fi
}

build_image
push_registry
