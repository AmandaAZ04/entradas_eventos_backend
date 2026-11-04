#!/usr/bin/env bash
# Ejecutar comandos Django con las mismas variables y usuario que Gunicorn.
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then
    echo "Usa sudo bash deploy/ec2/manage.sh <comando Django>" >&2
    exit 1
fi
if [[ "$#" -eq 0 ]]; then
    echo "Indica un comando: check, migrate, collectstatic, createsuperuser..." >&2
    exit 1
fi
cd /srv/entradas_eventos
exec runuser -u entradas -- venv/bin/python -c '
import os
import sys
from dotenv import dotenv_values
values = dotenv_values("/etc/entradas_eventos/entradas.env")
os.environ.update({k: v for k, v in values.items() if v is not None})
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "entradas_eventos.settings")
from django.core.management import execute_from_command_line
execute_from_command_line(["manage.py", *sys.argv[1:]])
' "$@"
