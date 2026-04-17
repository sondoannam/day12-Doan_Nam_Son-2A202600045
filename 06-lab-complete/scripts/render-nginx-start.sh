#!/bin/sh
set -eu

: "${PORT:=10000}"
: "${AGENT_UPSTREAM_HOST:?AGENT_UPSTREAM_HOST is required}"
: "${AGENT_UPSTREAM_PORT:?AGENT_UPSTREAM_PORT is required}"

NGINX_RESOLVER="$(awk '/^nameserver / { print $2; exit }' /etc/resolv.conf)"
export NGINX_RESOLVER

if [ -z "${NGINX_RESOLVER}" ]; then
  echo "Unable to determine DNS resolver from /etc/resolv.conf" >&2
  exit 1
fi

envsubst '${PORT} ${AGENT_UPSTREAM_HOST} ${AGENT_UPSTREAM_PORT} ${NGINX_RESOLVER}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'