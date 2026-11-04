#!/usr/bin/env bash
# Comprobaciones de lectura en la instancia, después de instalar los servicios.
set -euo pipefail
host="${1:?Uso: bash deploy/ec2/verificar.sh TU_IP_O_DOMINIO [http|https]}"
scheme="${2:-http}"
if [[ ! "$host" =~ ^[A-Za-z0-9.-]+$ ]] || [[ "$scheme" != http && "$scheme" != https ]]; then
    echo "Indica solo un host y el esquema http o https." >&2
    exit 1
fi
sudo systemctl is-active --quiet entradas_eventos nginx postgresql
sudo nginx -t
sudo -u www-data curl --fail --silent --show-error \
    --unix-socket /run/entradas_eventos/gunicorn.sock \
    -H "Host: $host" -o /dev/null http://localhost/api/eventos/
# --resolve comprueba también un dominio HTTPS desde la propia instancia.
for path in / /api/eventos/ /api/docs/ /api/schema/ /static/encore/store.css /static/admin/css/base.css /static/rest_framework/css/default.css; do
    curl --fail --silent --show-error --location \
        --resolve "$host:80:127.0.0.1" --resolve "$host:443:127.0.0.1" \
        -o /dev/null "$scheme://$host$path"
    printf 'OK %s\n' "$path"
done
status="$(curl --silent --show-error --location \
    --resolve "$host:80:127.0.0.1" --resolve "$host:443:127.0.0.1" \
    -o /dev/null -w '%{http_code}' "$scheme://$host/api/carro-tickets/")"
[[ "$status" == 401 ]] || { echo "Se esperaba 401 en el carro sin JWT; llegó $status" >&2; exit 1; }
echo "OK carro protegido sin JWT (401). Falta comprobar el acceso público desde tu navegador."
