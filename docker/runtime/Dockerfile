FROM --platform=$TARGETPLATFORM harbor.wujiaxing.top/library/ubuntu:24.04 

ENV LANG=en_US.UTF-8 \
    PYTHONPATH=/opt/trident/ \
    LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:/opt/instantclient_21_3 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_BREAK_SYSTEM_PACKAGES=true \
    PIP_NO_CACHE_DIR=true \
    PIP_DISABLE_PIP_VERSION_CHECK=true \
    PSYCOPG2_GAUSS=False \
    UV_NO_CACHE=true \
    UV_PROJECT_ENVIRONMENT=/usr/ \
    UV_SYSTEM_PYTHON=true \
    UV_BREAK_SYSTEM_PACKAGES=true \
    PYTHONDONTWRITEBYTECODE=1 \
    SUPERVISOR_LOGFILE_BACKUPS=180 \
    SUPERVISOR_LOGFILE_BY_DATE=D \
    MODE=WEB \
    WEB_NUM=4 \
    SERVICE_NUM=4 \
    NGINX_VERSION=1.28.0

WORKDIR /opt/trident

SHELL ["/bin/bash", "-c"]

RUN --mount=type=bind,source=./,target=/builder cp -a /builder/. /opt/trident/ && \
    set -o pipefail && \
	set -x && \
    ( userdel -r -f ubuntu || true ) && \
    useradd -s /bin/bash trident && \
    sed -i -E 's/(archive|prots).ubuntu.com/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/ubuntu.sources && \
    apt update -y && \
    DEBIAN_FRONTEND=noninteractive apt install --no-install-recommends -y \
        python3.12-dev \
        vim-tiny \
        gnupg \
        ca-certificates \
        tzdata \
        locales \
        build-essential \
        curl \
        wget \
        htop \
        gosu \
        netcat-traditional \
        postgresql-client \
        libpq-dev \
        # oracle client dependency
        libaio1t64 \
        unzip \
        # ldap
        libldap2-dev \
        libsasl2-dev && \
    # nginx
    curl https://nginx.org/keys/nginx_signing.key | gpg --dearmor | tee /usr/share/keyrings/nginx-archive-keyring.gpg >/dev/null && \
    source /etc/os-release && \
    ( echo -e "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] http://nginx.org/packages/mainline/ubuntu ${VERSION_CODENAME} nginx" \
        | tee /etc/apt/sources.list.d/nginx.list ) && \
    ( echo -e "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] http://nginx.org/packages/ubuntu ${VERSION_CODENAME} nginx" \
        | tee /etc/apt/sources.list.d/nginx-stable.list ) && \
    apt update -y && \
    APT_NGINX_VERSION=$(apt list -a nginx 2>/dev/null | grep ${NGINX_VERSION} | awk '{print $2}'| head -n1) && \
    DEBIAN_FRONTEND=noninteractive apt install --no-install-recommends -y \
        nginx=${APT_NGINX_VERSION} && \
    ln -sf /usr/bin/vim.tiny /usr/bin/vim && \
    ln -sf /usr/bin/python3.12 /usr/bin/python3 && \
    ln -sf /usr/bin/python3.12-config /usr/bin/python3-config && \
    locale-gen en_US.UTF-8 && \
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo 'Asia/Shanghai' >/etc/timezone && \
    # oracle client
    if [[ $(uname -i) == "aarch64" ]]; then \
        wget -qO /tmp/instantclient-basic-linux.arm64-19.10.0.0.0dbru.zip http://fm.paodingai.com/api/public/dl/A2p7Jy8J && \
        unzip /tmp/instantclient-basic-linux.arm64-19.10.0.0.0dbru.zip -d /opt/ && \
        mv /opt/instantclient_19_10 /opt/instantclient; \
    else \
        wget -qO /tmp/instantclient_21_3.tgz http://fm.paodingai.com/api/public/dl/ZCNDIONd && \
        tar -zxf /tmp/instantclient_21_3.tgz -C /opt/; \
    fi && \
    wget -qO - http://fm.paodingai.com/share/5525fcf729f1003a9ab7661f5668e60d776fcd1e8c94f36660475f1fded609f8?dl=1 | python3 - && \
    pip install --upgrade uv && \
    uv sync --group=ops && \
    mkdir -p /etc/supervisor/conf.d /var/log/supervisor /data /docker && \
    ( bash ./docker/modify_permission.sh || true ) && \
	apt purge --autoremove -y \
		unzip && \
    rm -rf /opt/trident/* /var/lib/apt/lists/* /etc/nginx/conf.d/* /tmp/* /root/.cache/pip/ ./docker/modify_permission.sh pyproject.toml uv.lock && \
    find /var/log -type f -delete
