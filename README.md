# Venta de Entradas para Eventos y Conciertos

Proyecto de evaluación de Desarrollo Backend desarrollado con Django REST Framework y PostgreSQL.

- **Estudiante:** Amanda Angélica Álvarez Álvarez
- **Sección:** IEC-N4-C1
- **Año:** 2026

## Descripción

Plataforma de venta de entradas con dos roles:

- **Espectador:** consulta eventos, agrega entradas a su carro, confirma compras y consulta sus tickets.
- **Organizador:** registra recintos, administra sus eventos y sectores, consulta sus ventas y cambia estados de compras.

## Tecnologías

- Python y Django.
- Django REST Framework.
- PostgreSQL.
- SimpleJWT.
- django-filter.
- drf-spectacular para Swagger/OpenAPI.

## Funcionalidades

- Inicio de sesión con tokens access y refresh.
- Claim de rol incluido en los tokens.
- Permisos según el rol del usuario.
- Catálogo público de eventos y sectores.
- Carro persistente asociado al usuario.
- Validación de stock al pagar.
- Compras con precios históricos.
- Emisión de entradas con UUID único.
- Cancelación con devolución de stock e invalidación de tickets.
- Registro de ingreso mediante el estado ENTREGADO.
- Filtros por nombre, artista, ciudad, fecha, precio y stock.
- Página principal con los datos del estudiante.
- Pruebas automáticas.

## Instalación en Windows

### 1. Requisitos

Instalar Python, Git y PostgreSQL.

### 2. Clonar el repositorio

```powershell
git clone https://github.com/AmandaAZ04/entradas_eventos_backend.git
cd entradas_eventos_backend
```

### 3. Crear el entorno virtual e instalar dependencias

Los siguientes comandos usan directamente el Python del entorno, por lo que no requieren activarlo:

```powershell
python -m venv env
.\env\Scripts\python.exe -m pip install -r requirements.txt
```

### 4. Crear la base de datos

En PostgreSQL, crear una base de datos llamada:

```text
entradas_eventos_db
```

### 5. Configurar las variables de entorno

Copiar el archivo de ejemplo:

```powershell
Copy-Item .env.example .env
```

Editar `.env` con la configuración local:

```dotenv
DJANGO_SECRET_KEY=colocar_una_clave_generada
DJANGO_DEBUG=True
DB_NAME=entradas_eventos_db
DB_USER=postgres
DB_PASSWORD=colocar_la_password_local
DB_HOST=localhost
DB_PORT=5432
```

Generar una clave para Django:

```powershell
.\env\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Copiar el resultado en `DJANGO_SECRET_KEY`.

### 6. Aplicar migraciones

```powershell
.\env\Scripts\python.exe manage.py migrate
```

### 7. Crear el administrador

```powershell
.\env\Scripts\python.exe manage.py createsuperuser
```

### 8. Iniciar el servidor

```powershell
.\env\Scripts\python.exe manage.py runserver
```

## Accesos locales

- Inicio: http://127.0.0.1:8000/
- Administrador: http://127.0.0.1:8000/admin/
- Swagger: http://127.0.0.1:8000/api/docs/
- OpenAPI: http://127.0.0.1:8000/api/schema/

## Preparación de datos

Desde el administrador:

1. Asignar el rol ORGANIZADOR al usuario que gestionará los eventos.
2. Crear un recinto.
3. Crear un evento activo con fecha futura y asignarle el organizador.
4. Crear sectores con precio y stock.
5. Crear un usuario con rol ESPECTADOR para probar compras.

El rol Organizador y el permiso de acceso al administrador de Django son configuraciones independientes.

## Autenticación JWT

Enviar usuario y contraseña a:

```text
POST /api/token/
```

Ejemplo:

```json
{
    "username": "nombre_de_usuario",
    "password": "password_del_usuario"
}
```

La respuesta contiene `access`, `refresh` y los datos básicos del usuario.

Para consumir rutas protegidas:

```text
Authorization: Bearer <access_token>
```

Para renovar el token:

```text
POST /api/token/refresh/
```

Enviar:

```json
{
    "refresh": "token_de_renovacion"
}
```

## Endpoints principales

| Método | Ruta | Acceso |
|---|---|---|
| GET | `/api/eventos/` | Público |
| GET | `/api/eventos/{id}/` | Público para eventos activos |
| GET | `/api/eventos/{id}/sectores/` | Público para eventos activos |
| POST | `/api/eventos/` | Organizador |
| PUT/PATCH/DELETE | `/api/eventos/{id}/` | Organizador propietario |
| GET/POST | `/api/recintos/` | Lectura pública y creación por organizador |
| GET/POST | `/api/sectores/` | Lectura pública y creación por organizador del evento |
| GET/POST | `/api/carro-tickets/` | Espectador |
| DELETE | `/api/carro-tickets/{id}/` | Espectador propietario |
| POST | `/api/compras/pagar/` | Espectador |
| GET | `/api/compras/` | Compras propias del espectador o ventas del organizador |
| GET | `/api/compras/{id}/` | Usuario autorizado para esa compra |
| GET | `/api/mis-entradas/` | Espectador |
| PATCH | `/api/compras/{id}/estado/` | Organizador del evento |

## Flujo de compra

1. El espectador agrega un sector y una cantidad al carro.
2. Agregar al carro no modifica el stock ni garantiza disponibilidad.
3. Al pagar, se comprueba la disponibilidad de todos los ítems.
4. Se genera una compra por evento y se conservan sus precios.
5. La compra pasa a PAGADO y se descuenta el stock.
6. Se genera una entrada con UUID por cada ticket.
7. Se vacían los ítems del carro, conservando el carro del usuario.

El checkout utiliza una transacción atómica y bloqueos de filas para coordinar los cambios de inventario.

**El pago es simulado para fines académicos. No se realizan cobros ni se integra una pasarela de pago real.**

## Estados

- **PENDIENTE:** estado inicial de la compra.
- **PAGADO:** compra confirmada con stock descontado.
- **CANCELADO:** stock devuelto y entradas invalidadas.
- **ENTREGADO:** entradas marcadas como utilizadas.

El organizador puede cambiar una compra PAGADA a CANCELADO o ENTREGADO. Repetir el mismo estado no duplica las operaciones. Una compra ENTREGADA no puede cancelarse.

## Filtros

Ejemplos:

```text
/api/eventos/?nombre=concierto
/api/eventos/?artista=banda
/api/eventos/?ciudad=Santiago
/api/sectores/?precio_min=20000&precio_max=50000
/api/sectores/?stock_min=1
```

## Pruebas automáticas

Ejecutar:

```powershell
.\env\Scripts\python.exe manage.py test api --verbosity 2
```

Las diez pruebas verifican JWT, permisos, privacidad y persistencia del carro, stock, pago, emisión de entradas, cancelación y entrega.

Django utiliza una base de datos de pruebas separada. El usuario de PostgreSQL debe tener permiso para crearla.

## Archivos de configuración

- `requirements.txt`: dependencias del proyecto.
- `.env.example`: ejemplo de configuración sin credenciales reales.
- `.env`: configuración privada local, excluida de Git.
- `env/`: entorno virtual local, excluido de Git.