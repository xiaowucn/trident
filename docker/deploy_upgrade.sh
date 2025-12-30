#!/usr/bin/env bash

set -ex

set -o pipefail

pip install --upgrade uv --no-cache-dir
UV_NO_CACHE=true UV_PROJECT_ENVIRONMENT=/usr/ UV_SYSTEM_PYTHON=true UV_BREAK_SYSTEM_PACKAGES=true uv sync --group=ops
if [[ ${PSYCOPG2_GAUSS,,} == "true" ]]; then
  uv pip install --index-url http://100.64.0.1:3141/cheftin/pypi --trusted-host 100.64.0.1 --target=/usr/lib/paoding/dist-packages/ psycopg2-gauss --upgrade --no-cache
  export PYTHONPATH=/usr/lib/paoding/dist-packages/:${PYTHONPATH}
fi

gosu trident inv db.upgrade

supervisorctl start all
supervisorctl signal hup trident:
