#!/usr/bin/env bash
#!/bin/bash

BIN_DIR=$(dirname $0)
PROJECT_ROOT=$(perl -mCwd -e "print Cwd::abs_path('$BIN_DIR/..')")

get_config() {
    cd ${PROJECT_ROOT} >/dev/null 2>&1
    RESULT=$(python -c "from user_proxy.config import get_config; print(get_config('$1') or \"\")" 2>/dev/null)
    cd - >/dev/null 2>&1
    echo ${RESULT}
}


USER=$(get_config "webif.postgresql.user")
DB_NAME=$(get_config "webif.postgresql.db_name")
PORT=$(get_config "webif.postgresql.port")
DB_HOST=$(get_config "webif.postgresql.host")
PASSWORD=$(get_config "webif.postgresql.password")

REVISION=$1
cd $PROJECT_ROOT
alembic -c migrations/alembic.ini -x dburl=postgresql+psycopg2://${USER}@${DB_HOST}:${PORT}/${DB_NAME} downgrade ${REVISION}
