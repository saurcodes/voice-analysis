#!/bin/sh
# Runs as the frontend container's entrypoint (see Dockerfile): writes the runtime
# /config.json that src/config.ts fetches at startup, renders the nginx config template
# (frontend/nginx.conf.template) with the same Keycloak host baked into its CSP, and then
# execs nginx. This is what lets one built image serve any environment: the Keycloak host is
# an env var on the `frontend` compose service, not a Vite build-time value.
set -eu

KEYCLOAK_URL=${KEYCLOAK_URL:-http://localhost:8080}
KEYCLOAK_REALM=${KEYCLOAK_REALM:-vocal-coach}
KEYCLOAK_CLIENT_ID=${KEYCLOAK_CLIENT_ID:-vocal-coach-web}

# These three values are interpolated into config.json (as JSON string values, unescaped) and
# into the CSP header (as bare URL text, see nginx.conf.template); a double quote in either
# would break out of its context, so reject it outright rather than trying to escape it.
for name in KEYCLOAK_URL KEYCLOAK_REALM KEYCLOAK_CLIENT_ID; do
  eval "value=\$$name"
  case "$value" in
    *'"'*)
      echo "docker-entrypoint.sh: \$$name must not contain a double-quote character" >&2
      exit 1
      ;;
  esac
done

cat > /usr/share/nginx/html/config.json <<EOF
{"keycloakUrl": "${KEYCLOAK_URL}", "keycloakRealm": "${KEYCLOAK_REALM}", "keycloakClientId": "${KEYCLOAK_CLIENT_ID}"}
EOF

export KEYCLOAK_URL
envsubst '${KEYCLOAK_URL}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'
