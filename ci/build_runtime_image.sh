#!/usr/bin/env bash

set -e
export DOCKER_BUILDKIT=1

IMAGE_VERSION="latest"

build_image() {
  if ! docker build --pull --progress=plain --platform="${BUILD_PLATFORM}" --squash --no-cache --tag="${IMAGE_NAME}:${IMAGE_VERSION}" .; then
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

BUILD_PLATFORM="linux/amd64"
IMAGE_NAME="trident-py312-runtime-amd64"
ln -sf docker/runtime/Dockerfile ./
ln -sf docker/runtime/dockerignore .dockerignore
build_image
push_registry

# build for arm64
BUILD_PLATFORM="linux/arm64"
IMAGE_NAME="trident-py312-runtime-arm64"
ln -sf docker/runtime/Dockerfile ./
ln -sf docker/runtime/dockerignore .dockerignore
build_image
push_registry

if [ -n "${REGISTRY_URL}" ]; then
  docker buildx imagetools create -t "${REGISTRY_URL}/trident-py312-runtime:latest" \
      "${REGISTRY_URL}/trident-py312-runtime-amd64:latest" \
      "${REGISTRY_URL}/trident-py312-runtime-arm64:latest"
fi
