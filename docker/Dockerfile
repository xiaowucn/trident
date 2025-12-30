FROM --platform=$TARGETPLATFORM registry.cheftin.cn/p/trident-py312-runtime as builder

WORKDIR /opt/trident

ARG env=docker

ENV ENV=${env}

RUN --mount=type=bind,source=./,target=/builder cp -a /builder/. /opt/trident/ && \
    apt update -y && \
    DEBIAN_FRONTEND=noninteractive apt install --no-install-recommends -y \
        build-essential \
        shc && \
    pip install --upgrade uv && \
    uv sync --group=ops && \
    python3 -m user_proxy.config && \
    ./docker/cyc && \
    rm -rf ./docker/cyc config/*.yml

FROM --platform=$TARGETPLATFORM registry.cheftin.cn/p/trident-py312-runtime

WORKDIR /opt/trident

ARG env=docker

ENV ENV=${env} \
    LANG=en_US.UTF-8 \
    PYTHONPATH=/opt/trident

SHELL ["/bin/bash", "-c"]

RUN --mount=type=bind,from=builder,source=/opt/trident,target=/builder cp -a /builder/. /opt/trident/ && \
    set -o pipefail && \
    apt update -y && \
    apt upgrade -y && \
    DEBIAN_FRONTEND=noninteractive apt install --no-install-recommends -y \
        build-essential && \
    # install default-jre will be remove by build_image.sh, don't change this line
    DEBIAN_FRONTEND=noninteractive apt install --no-install-recommends -y default-jre && \
    pip install --upgrade uv && \
    uv sync --group=ops && \
    if [[ $(uname -i) == "aarch64" ]]; then \
        printf 'skip install psycopg2-gauss on arm64 !!!!!!!!!' ; \
    else \
        uv pip install --index-url http://100.64.0.1:3141/cheftin/pypi --trusted-host 100.64.0.1 --target=/usr/lib/paoding/dist-packages/ psycopg2-gauss --upgrade --no-cache ; \
    fi && \
    apt autoremove -y --purge \
        build-essential && \
    mkdir -p /var/lib/apt/lists/partial /data && \
    chmod +x docker/patch_installer.sh docker/docker-entrypoint.sh && \
    cp -rf docker/* /docker/ && \
    cp -rf /docker/supervisor/supervisord.conf /etc/supervisor/supervisord.conf && \
    ( ./docker/modify_permission.sh || true )  && \
    rm -rf /var/lib/apt/lists/* /opt/trident/requirements libs /root/.cache/pip/ ./docker pyproject.toml uv.lock

ENTRYPOINT ["/docker/docker-entrypoint.sh"]
HEALTHCHECK --interval=15s --timeout=30s --retries=3 CMD ["/usr/bin/python3", "/docker/healthcheck.pyc"]
