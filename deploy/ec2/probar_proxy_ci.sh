#!/usr/bin/env bash
# Prueba real del proxy en un runner Linux; no instala servicios en EC2.
set -euo pipefail
test_dir="$(mktemp -d)"
gunicorn_pid=""
cleanup() {
    if [[ -f "$test_dir/nginx.pid" ]]; then
        nginx -p "$test_dir/" -c "$test_dir/nginx.conf" -s quit || true
    fi
    if [[ -n "$gunicorn_pid" ]]; then
        kill "$gunicorn_pid" 2>/dev/null || true
        wait "$gunicorn_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT
export PROXY_TEST_DIR="$test_dir"
python - <<'PY'
import os
from pathlib import Path
root = Path(os.environ['PROXY_TEST_DIR'])
site = Path('deploy/ec2/nginx.conf').read_text()
site = site.replace('listen 80;', 'listen 8080;')
site = site.replace('TU_IP_O_DOMINIO', 'localhost')
site = site.replace('/run/entradas_eventos/gunicorn.sock', str(root / 'gunicorn.sock'))
site = site.replace('/var/www/entradas_eventos/static/', os.environ['DJANGO_STATIC_ROOT'] + '/')
site = site.replace('/var/log/nginx/', str(root) + '/')
(root / 'nginx.conf').write_text(
    f'pid {root}/nginx.pid;\nerror_log stderr;\nevents {{}}\nhttp {{\n'
    'include /etc/nginx/mime.types;\n'
    f'client_body_temp_path {root}/body;\nproxy_temp_path {root}/proxy;\n'
    f'fastcgi_temp_path {root}/fastcgi;\nuwsgi_temp_path {root}/uwsgi;\n'
    f'scgi_temp_path {root}/scgi;\n' + site + '\n}\n'
)
PY
gunicorn --workers 2 --bind "unix:$test_dir/gunicorn.sock" \
    --timeout 90 --access-logfile - --error-logfile - entradas_eventos.wsgi:application &
gunicorn_pid="$!"
for attempt in {1..30}; do
    if curl --fail --silent --unix-socket "$test_dir/gunicorn.sock" \
        -H 'Host: localhost' http://localhost/api/eventos/ >/dev/null; then
        break
    fi
    sleep 1
done
curl --fail --silent --show-error --unix-socket "$test_dir/gunicorn.sock" \
    -H 'Host: localhost' http://localhost/api/eventos/ >/dev/null
nginx -p "$test_dir/" -c "$test_dir/nginx.conf" -t
nginx -p "$test_dir/" -c "$test_dir/nginx.conf"
for path in / /api/eventos/ /api/docs/ /api/schema/ /static/encore/store.css /static/admin/css/base.css /static/rest_framework/css/default.css; do
    curl --fail --silent --show-error -o /dev/null "http://localhost:8080$path"
    printf 'OK proxy %s\n' "$path"
done
status="$(curl --silent --show-error -o /dev/null -w '%{http_code}' http://localhost:8080/api/carro-tickets/)"
[[ "$status" == 401 ]] || { echo "Carro sin JWT: se esperaba 401; llegó $status" >&2; exit 1; }
echo 'OK proxy: carro protegido (401)'
