#!/bin/bash

pip install --upgrade uv
uv sync --group=ops
if [[ ${PSYCOPG2_GAUSS,,} == "true" ]]; then
  uv pip install --index-url http://100.64.0.1:3141/cheftin/pypi --trusted-host 100.64.0.1 --target=/usr/lib/paoding/dist-packages/ psycopg2-gauss --upgrade --no-cache
fi

rm -rf /docker/*
mkdir -p /docker/nginx /docker/supervisor
cp -rf /opt/trident/docker/docker-entrypoint.sh /docker/docker-entrypoint.sh
cp -rf /opt/trident/docker/nginx/* /docker/nginx/
cp -rf /opt/trident/docker/supervisor/* /docker/supervisor/
cp -rf /docker/supervisor/supervisord.conf /etc/supervisor/supervisord.conf
chmod +x /docker/docker-entrypoint.sh
bash -x /docker/docker-entrypoint.sh "$@"
