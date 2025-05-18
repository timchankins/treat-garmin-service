#!/bin/bash
# wait-for-db.sh

set -e

host="$1"
port="$2"
shift 2
cmd="$@"

# Wait for the database server to become available
until pg_isready -h "$host" -p "$port" -U "${POSTGRES_DB_USER}" > /dev/null 2>&1; do
  >&2 echo "Postgres is unavailable - sleeping"
  sleep 1
done

>&2 echo "Postgres is up - executing command"
exec $cmd
