# Desplegar Encore en AWS EC2 con Gunicorn y Nginx

Adaptación de la receta de clase al repositorio `AmandaAZ04/entradas_eventos_backend`.
Se despliega el proyecto existente: no hay que crear ToDoList ni reemplazar sus modelos.

**Estado:** estos archivos preparan el despliegue. Tenerlos en GitHub no crea una
instancia EC2 ni publica automáticamente la aplicación.

## 1. Crear la instancia

En AWS, elige una región y crea una instancia llamada `entradas-eventos` con:

- Ubuntu Server **24.04 LTS**, arquitectura x86_64. Su Python 3.12 es compatible
  con Django 6.1 del proyecto. La receta usa Ubuntu 22.04 y Python 3.10, que no
  sirve para estas dependencias.
- Una instancia pequeña adecuada a tu cuenta; PostgreSQL y dos procesos de
  Gunicorn comparten su memoria. Comprueba el consumo antes de aumentar tráfico.
- Un par de claves SSH; guarda el archivo `.pem` en una carpeta privada de Windows.
- VPC y subred pública con ruta a Internet y asignación de IPv4 pública.
- Grupo de seguridad: TCP 22 desde **tu IP**, TCP 80 público y TCP 443 cuando
  habilites HTTPS. PostgreSQL (5432) y Gunicorn no necesitan acceso entrante público.
- ICMP desde tu IP es opcional si quieres comprobar ping.

Asocia una Elastic IP si necesitas una dirección estable. Verifica los precios y
los créditos de tu cuenta antes de crear recursos: EC2, almacenamiento e IPv4
pública pueden generar cargos. La capa gratuita no debe darse por garantizada.

## 2. Conectar desde Windows

Sustituye la ruta y la IP por las reales. No subas el `.pem` al repositorio.

```powershell
$claveEC2 = 'C:\ruta\privada\entradas-eventos.pem'
icacls $claveEC2 /inheritance:r
icacls $claveEC2 /grant:r "$($env:USERNAME):(R)"
ssh -i $claveEC2 ubuntu@TU_IP_PUBLICA
```

Comprueba la huella SSH de la instancia en AWS antes de aceptar la primera conexión.
Los siguientes comandos se ejecutan en **Ubuntu por SSH**, salvo indicación contraria.

## 3. Instalar los paquetes y descargar el proyecto

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git nginx postgresql
python3 --version
sudo adduser --system --group --home /srv/entradas_eventos --no-create-home entradas
sudo install -d -o ubuntu -g entradas -m 2750 /srv/entradas_eventos
git clone https://github.com/AmandaAZ04/entradas_eventos_backend.git /srv/entradas_eventos
cd /srv/entradas_eventos
```

Si los cambios de despliegue todavía están en una pull request, cambia a su rama
con `git switch deploy/ec2-gunicorn-nginx` antes de seguir.

```bash
python3 -m venv venv
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements-deploy.txt
sudo chgrp -R entradas /srv/entradas_eventos
sudo chmod -R g+rX,o-rwx /srv/entradas_eventos
```

La carpeta debe estar vacía antes de `git clone`. Si ya existe una instalación,
revisa su estado y usa la sección de actualización; no la borres ni la sobrescribas.

## 4. Crear PostgreSQL

```bash
sudo systemctl enable --now postgresql
sudo -u postgres psql
```

Dentro de `psql`, crea un usuario sin privilegios administrativos y la base:

```sql
CREATE USER entradas_app;
\password entradas_app
CREATE DATABASE entradas_eventos_db OWNER entradas_app;
\q
```

`\password` solicita una contraseña sin dejarla escrita en el comando. Guárdala
para la configuración del siguiente paso. La base queda local: no abras 5432 en AWS.

## 5. Configurar las variables privadas

```bash
sudo install -d -o root -g entradas -m 0750 /etc/entradas_eventos
sudo install -o root -g entradas -m 0640 deploy/ec2/entradas.env.example /etc/entradas_eventos/entradas.env
venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(64))'
sudo nano /etc/entradas_eventos/entradas.env
```

En el archivo privado, reemplaza los marcadores de clave, contraseña y host. Usa
la clave aleatoria recién generada. `DJANGO_ALLOWED_HOSTS` contiene IP/dominio
sin esquema; `DJANGO_CSRF_TRUSTED_ORIGINS` contiene el origen completo, por ejemplo
`http://203.0.113.10`. La IP de ese ejemplo es ilustrativa: usa tu dirección real.
Mantén `DJANGO_DEBUG=False` y `WEBPAY_ENVIRONMENT=integration`.

No hace falta crear un `.env` dentro del repositorio. El servicio carga las
variables desde `/etc`; `manage.sh` carga ese mismo archivo para los comandos Django.
El ejemplo funciona con systemd y python-dotenv: no agregues `export`, sustituciones
`$VARIABLE` ni comandos de shell. Utiliza valores literales entre comillas simples.

## 6. Migrar y recopilar los archivos estáticos

```bash
sudo install -d -o entradas -g www-data -m 0755 /var/www/entradas_eventos
sudo install -d -o entradas -g www-data -m 0755 /var/www/entradas_eventos/static
sudo bash deploy/ec2/manage.sh check
sudo bash deploy/ec2/manage.sh migrate
sudo bash deploy/ec2/manage.sh collectstatic --noinput
sudo bash deploy/ec2/manage.sh createsuperuser
```

Opcional para presentar la cartelera ficticia:

```bash
sudo bash deploy/ec2/manage.sh cargar_demo
```

Las migraciones crean el esquema de una base nueva; no transfieren los datos de
tu computador. Si necesitas datos existentes, prepara una copia de PostgreSQL y
su restauración por separado. No publiques copias de bases de datos en GitHub.

`STATIC_ROOT` apunta a `/var/www/entradas_eventos/static`; el código fuente conserva
`static/encore/`. No uses el mismo directorio para origen y destino de `collectstatic`.

## 7. Instalar el servicio Gunicorn

```bash
sudo install -o root -g root -m 0644 deploy/ec2/entradas_eventos.service /etc/systemd/system/entradas_eventos.service
sudo systemctl daemon-reload
sudo systemctl enable --now entradas_eventos
sudo systemctl status entradas_eventos --no-pager
```

El servicio usa `entradas_eventos.wsgi:application`, dos workers y un socket Unix
en `/run/entradas_eventos/gunicorn.sock`. systemd recrea su directorio en cada
arranque. Gunicorn y Nginx comparten acceso por el grupo `www-data`.

## 8. Instalar el proxy Nginx

```bash
sudo install -o root -g root -m 0644 deploy/ec2/nginx.conf /etc/nginx/sites-available/entradas_eventos
sudo nano /etc/nginx/sites-available/entradas_eventos
```

Reemplaza `TU_IP_O_DOMINIO` por el mismo host configurado en Django. Activa el sitio:

```bash
sudo ln -s /etc/nginx/sites-available/entradas_eventos /etc/nginx/sites-enabled/entradas_eventos
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
bash deploy/ec2/verificar.sh TU_IP_O_DOMINIO
```

El sitio predeterminado de Ubuntu puede conservarse: el host exacto de Encore
tiene prioridad. Si el enlace ya existe, omite `ln -s`; comprueba su destino con
`readlink /etc/nginx/sites-enabled/entradas_eventos`.

Visita desde tu computador:

- `http://TU_IP_O_DOMINIO/`: tienda Encore.
- `http://TU_IP_O_DOMINIO/api/eventos/`: catálogo público.
- `http://TU_IP_O_DOMINIO/api/docs/`: Swagger.
- `http://TU_IP_O_DOMINIO/admin/`: administración.

Comprueba que carguen los estilos de la tienda, Admin y DRF. Un catálogo vacío
es válido si todavía no cargaste eventos. Prueba el login y el carro después de
habilitar HTTPS; evita enviar contraseñas por HTTP en una red pública.

## 9. Habilitar HTTPS con un dominio

Apunta un registro DNS A del dominio a la Elastic IP. Abre TCP 443 en el grupo
de seguridad y usa ese dominio en `server_name`, `DJANGO_ALLOWED_HOSTS` y la URL
de retorno de Webpay. Instala un certificado para ese dominio:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d TU_DOMINIO
sudo certbot renew --dry-run
sudo nano /etc/entradas_eventos/entradas.env
```

Configura el origen como `https://TU_DOMINIO`, el retorno como
`https://TU_DOMINIO/pago/retorno/`, y estas opciones:

```dotenv
DJANGO_BEHIND_HTTPS_PROXY=True
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SECURE_COOKIES=True
```

Nginx sobrescribe `X-Forwarded-Proto` y Gunicorn solo escucha por el socket privado.
Después de verificar el certificado:

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl restart entradas_eventos
sudo bash deploy/ec2/manage.sh check --deploy
bash deploy/ec2/verificar.sh TU_DOMINIO https
```

Revisa cualquier advertencia de `check --deploy`; HSTS debe activarse solo después
de comprobar que el dominio funciona siempre por HTTPS. El despliegue académico
no activa cobros comerciales: Webpay se mantiene en integración. Para cobros reales
siguen aplicando los requisitos comerciales y técnicos del README principal.

## 10. Estructura Linux y diagnóstico

| Ruta | Función en este proyecto |
|---|---|
| `/home/ubuntu` | Carpeta del usuario que entra por SSH |
| `/srv/entradas_eventos` | Código y entorno virtual de la aplicación |
| `/etc/entradas_eventos/entradas.env` | Configuración privada |
| `/etc/systemd/system/entradas_eventos.service` | Servicio Gunicorn |
| `/etc/nginx/sites-available/entradas_eventos` | Configuración de Nginx |
| `/run/entradas_eventos/gunicorn.sock` | Comunicación temporal Nginx-Gunicorn |
| `/var/www/entradas_eventos/static` | CSS/JS recopilados |
| `/var/log/nginx/entradas_eventos_*.log` | Registros de Nginx |
| `journalctl -u entradas_eventos` | Registros de Gunicorn |
| `/var/lib/postgresql` | Datos administrados por PostgreSQL |

Esta distribución aplica la imagen de directorios Linux: `/etc` configura, `/srv`
aloja el servicio, `/run` contiene datos temporales de ejecución y `/var` datos
variables. No se necesitan cambios en `/boot`, `/dev`, `/proc` ni `/sys`.

```bash
sudo journalctl -u entradas_eventos -n 80 --no-pager
sudo tail -n 50 /var/log/nginx/entradas_eventos_error.log
sudo systemctl status entradas_eventos nginx postgresql --no-pager
namei -l /run/entradas_eventos/gunicorn.sock
sudo -u www-data curl --unix-socket /run/entradas_eventos/gunicorn.sock -H 'Host: TU_IP_O_DOMINIO' http://localhost/api/eventos/
```

- **502:** comprueba servicio, socket y permisos de sus directorios.
- **400 / DisallowedHost:** corrige el host en el archivo privado y reinicia Gunicorn.
- **403 al ingresar al Admin:** revisa el origen CSRF y el esquema HTTP/HTTPS.
- **CSS sin cargar:** ejecuta `collectstatic`, comprueba `alias` y los permisos
  de `/var/www/entradas_eventos/static`.
- **Conexión rechazada a PostgreSQL:** revisa servicio, usuario, contraseña y DB_HOST.
- **Timeout desde Internet:** revisa la IP, la subred pública y los puertos del grupo
  de seguridad. No lo resuelvas exponiendo PostgreSQL o Gunicorn.

No uses permisos `666`/`777` ni desactives la validación de certificados para
resolver errores. El socket no necesita estar dentro de `/home/ubuntu`.

## Actualizar una instalación existente

Haz una copia de PostgreSQL antes de migraciones que cambien datos. Luego:

```bash
cd /srv/entradas_eventos
git status --short
git pull --ff-only
venv/bin/python -m pip install -r requirements-deploy.txt
sudo chgrp -R entradas /srv/entradas_eventos
sudo chmod -R g+rX,o-rwx /srv/entradas_eventos
sudo bash deploy/ec2/manage.sh check
sudo bash deploy/ec2/manage.sh migrate
sudo bash deploy/ec2/manage.sh collectstatic --noinput
sudo systemctl restart entradas_eventos
sudo nginx -t
sudo systemctl reload nginx
```

Si cambiaste el archivo `.service` o la plantilla Nginx del repositorio, vuelve a
instalar sus archivos como en los pasos 7 y 8, conservando el host y el certificado
de la instalación. No reemplaces el archivo privado con el ejemplo.

## Referencias

- Receta EC2 con Gunicorn y Nginx entregada en clase, adaptada a Encore.
- Imagen de estructura de directorios Linux de ByteByteGo entregada junto a la receta.
- [Compatibilidad Django 6.1 / Python](https://docs.djangoproject.com/en/6.1/releases/6.1/).
- [Despliegue Gunicorn con Nginx y systemd](https://gunicorn.org/deploy/).
- [Checklist de despliegue Django](https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/).
- [Reglas de seguridad EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-rules-reference.html).
- [Precios de IPv4 pública](https://aws.amazon.com/vpc/pricing/).
