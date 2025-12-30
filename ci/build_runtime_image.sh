#!/usr/bin/env bash

set -e

# 1. 强制关闭 BuildKit (解决证书报错的关键)
export DOCKER_BUILDKIT=0

IMAGE_VERSION="latest"
# 注意：旧版构建器不需要这个变量了，依赖宿主机架构
IMAGE_NAME="trident-py312-runtime-arm64"

# 准备 Dockerfile
ln -sf docker/runtime/Dockerfile ./
ln -sf docker/runtime/dockerignore .dockerignore

# 2. 【核心修复】清洗 Dockerfile
# 如果有 REGISTRY_URL，替换仓库地址
if [ -n "${REGISTRY_URL}" ]; then
    echo "Force updating registry url in Dockerfile to: ${REGISTRY_URL}"
    sed -i "s|registry.cheftin.cn/hub|${REGISTRY_URL}|g" Dockerfile
    sed -i "s|harbor.wujiaxing.top/library|${REGISTRY_URL}|g" Dockerfile
fi

# 【新增】删除 Legacy Builder 不支持的 BuildKit 参数
# 将 "FROM --platform=$TARGETPLATFORM xxx" 替换为 "FROM xxx"
echo "Removing BuildKit specific flags from Dockerfile..."
sed -i 's/--platform=$TARGETPLATFORM //g' Dockerfile

build_image() {
  echo "Start building image..."
  # 3. 构建命令：移除了所有不兼容参数，保留 --squash
  if ! docker build --pull --squash --no-cache --tag="${IMAGE_NAME}:${IMAGE_VERSION}" .; then
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
