#!/usr/bin/env bash

set -e

# 【关键修改 1】强制关闭 BuildKit
# BuildKit 会忽略 insecure-registries 配置，必须关掉它才能解决 SSL 证书报错
export DOCKER_BUILDKIT=0

IMAGE_VERSION="latest"
BUILD_PLATFORM="linux/arm64"
IMAGE_NAME="trident-py312-runtime-arm64"

# 准备 Dockerfile
ln -sf docker/runtime/Dockerfile ./
ln -sf docker/runtime/dockerignore .dockerignore

# 【关键修改 2】暴力替换 Dockerfile 里的仓库地址
# 不管你代码里写的是什么，这里直接用 sed 替换成 GoCD 传入的 harbor.wujiaxing.top
if [ -n "${REGISTRY_URL}" ]; then
    echo "Force updating registry url in Dockerfile to: ${REGISTRY_URL}"
    # 兼容两种可能写死的情况，全部替换
    sed -i "s|registry.cheftin.cn/hub|${REGISTRY_URL}|g" Dockerfile
    sed -i "s|harbor.wujiaxing.top/library|${REGISTRY_URL}|g" Dockerfile
fi

build_image() {
  # 【关键修改 3】移除不兼容参数
  # 1. 移除了 --platform="${BUILD_PLATFORM}" (关闭 BuildKit 后不支持该参数，且你本机就是 arm64，不需要指定)
  # 2. 移除了 --progress=plain (这是 BuildKit 的参数)
  # 3. 保留了 --squash (因为你的 docker info 显示 Experimental: true，旧版构建器支持它)
  echo "Start building image..."
  if ! docker build --pull --squash --no-cache --tag="${IMAGE_NAME}:${IMAGE_VERSION}" .; then
    echo 'build images error'
    exit 1
  fi
}

push_registry() {
  if [ -n "${REGISTRY_URL}" ]; then
    # 注意：这里逻辑没变，但建议清理镜像时更加严谨
    docker rmi "${REGISTRY_URL}/${IMAGE_NAME}":0.0.$((GO_PIPELINE_COUNTER - 2)) || true
    docker tag "${IMAGE_NAME}:${IMAGE_VERSION}" "${REGISTRY_URL}/${IMAGE_NAME}:${IMAGE_VERSION}"
    docker push "${REGISTRY_URL}/${IMAGE_NAME}:${IMAGE_VERSION}"
  fi
}

build_image
push_registry
