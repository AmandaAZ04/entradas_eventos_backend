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
- Filtros por categoría, nombre, artista, ciudad, fecha, precio y stock.
- Registro con nombre, apellido, RUT validado con módulo 11 o documento extranjero.
- Email único sin distinguir mayúsculas y contraseña con reglas de complejidad.
- Integración Webpay Plus con el SDK oficial de Transbank.
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
| POST | `/api/compras/pagar/` | Espectador, crea sesión Webpay |
| POST | `/api/compras/conciliar/` | Espectador, consulta sus pagos pendientes |
| POST | `/api/registro/` | Público, crea únicamente espectadores |
| GET | `/api/compras/` | Compras propias del espectador o ventas del organizador |
| GET | `/api/compras/{id}/` | Usuario autorizado para esa compra |
| GET | `/api/mis-entradas/` | Espectador |
| PATCH | `/api/compras/{id}/estado/` | Organizador del evento |

## Flujo de compra

1. El espectador agrega sectores y cantidades a su carro persistente, sin descontar stock.
2. Checkout verifica disponibilidad y conserva precios en compras PENDIENTES, una por evento y vinculadas a un Pago.
3. Transbank crea una sesión; solo entonces se vacían los ítems del carro. Un error al iniciar conserva el carro completo.
4. El navegador envía `token_ws` por POST al checkout HTTPS de Transbank. Los datos bancarios nunca pasan por Encore.
5. Webpay retorna por GET o POST a `/pago/retorno/`. El servidor consulta/confirma con el SDK y compara orden, sesión, monto, código de respuesta y estado.
6. Solo una autorización válida cambia las compras a PAGADO, descuenta stock y emite un UUID por ticket, dentro de una transacción PostgreSQL.
7. Un retorno repetido no emite entradas adicionales. Un pago rechazado o cancelado no descuenta inventario.
8. Al cancelar una compra pagada, Webpay debe confirmar la devolución antes de restituir stock e invalidar entradas. Una devolución incierta se guarda para revisión, sin repetirla automáticamente.

El checkout utiliza una transacción atómica y bloqueos de filas para coordinar los cambios de inventario.

**Webpay está integrado en ambiente de integración. Se abre la pantalla oficial de Transbank, pero no se cobra dinero real. Las pruebas automatizadas usan respuestas controladas del proveedor; también se comprobó una sesión real de integración y su cancelación en el navegador, sin ingresar tarjetas.**

La reserva temporal de checkout dura 15 minutos y se calcula desde compras pendientes, sin reducir el campo stock. Se bloquean sectores en orden estable al crear sesiones y al emitir tickets. Si una reserva vencida pierde disponibilidad y el proveedor ya autorizó, se solicita reversa; una respuesta incierta requiere conciliación comercial y no emite entradas.

### Recuperar un pago pendiente

El espectador puede usar «Consultar pago pendiente en Webpay» dentro de Mis compras. El endpoint `POST /api/compras/conciliar/` consulta exclusivamente sus pagos y no confirma sesiones bancarias sin autorización. También puede ejecutarse desde el servidor:

```powershell
.\env\Scripts\python.exe manage.py conciliar_pagos
```

Una devolución con estado REVISION debe contrastarse con el portal comercial de Transbank. No se debe borrar el intento ni repetir el reembolso sin comprobar el resultado del proveedor.

### Activar cobros comerciales

Requiere cuenta de comercio Webpay, validación/puesta en producción con Transbank y un despliegue HTTPS público. Configurar las credenciales privadas únicamente en `.env`:

```dotenv
WEBPAY_ENVIRONMENT=production
WEBPAY_COMMERCE_CODE=tu_codigo_comercial
WEBPAY_API_KEY=tu_clave_privada
WEBPAY_RETURN_URL=https://tu-dominio/pago/retorno/
DJANGO_ALLOWED_HOSTS=tu-dominio
DJANGO_DEBUG=False
```

No basta cambiar el ambiente: se deben configurar HTTPS, base de datos de producción, supervisión y conciliación periódica. Los conciertos `es_demo=True` están bloqueados para cobros reales. Registra eventos auténticos y autorizados antes de habilitar ventas comerciales. El proyecto local no está certificado ni desplegado como comercio real.

Referencia: [SDK oficial de Transbank](https://github.com/TransbankDevelopers/transbank-sdk-python) y [ejemplo oficial Webpay Plus en Python](https://proyecto-ejemplo-python.transbankdevelopers.cl/webpay-plus/).

## Estados

- **PENDIENTE:** estado inicial de la compra.
- **PAGADO:** compra confirmada con stock descontado.
- **CANCELADO:** stock devuelto y entradas invalidadas.
- **ENTREGADO:** entradas marcadas como utilizadas.

El organizador puede cambiar una compra PAGADA a CANCELADO o ENTREGADO. Repetir el mismo estado no duplica las operaciones. Una compra ENTREGADA no puede cancelarse.

## Filtros

Ejemplos:

```text
/api/eventos/?categoria=KPOP
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

Las 42 pruebas verifican JWT/refresh/roles, permisos, persistencia desde otro cliente, privacidad, filtros, precios históricos, múltiples eventos, validaciones de registro, Webpay aprobado/rechazado/cancelado/incierto, emisión única, reembolso y entrega. Una prueba usa conexiones PostgreSQL concurrentes para disputar el último ticket y repetir simultáneamente la confirmación.

Django utiliza una base de datos de pruebas separada. El usuario de PostgreSQL debe tener permiso para crearla.

## Tienda visual Encore

La página principal permite buscar eventos, seleccionar sector y cantidad, crear una cuenta de espectador, iniciar sesión, gestionar el carro y continuar al checkout de Webpay. Las entradas y el historial se consultan desde “Mi cuenta”. Los organizadores pueden consultar sus ventas y cancelar o marcar el ingreso de una compra desde el mismo menú.

Para cargar trece eventos ilustrativos de TVXQ, ALPHA DRIVE ONE, Taylor Swift, Billie Eilish, DAY6, TXT, BABYMONSTER, aespa, NCT WISH, Santos Bravos, Red Velvet, ZEROBASEONE y Wanna One:

```powershell
.\env\Scripts\python.exe manage.py cargar_demo
```

Este comando no sobrescribe eventos existentes ni repone stock de eventos ya cargados. Solo completa la categoría de los eventos demo antiguos que seguían clasificados como Otros. Los conciertos demo están identificados como ficticios; no representan fechas ni ventas oficiales. Las fotografías externas tienen sus fuentes en el footer y requieren conexión a Internet.

En el administrador puede configurarse `imagen_url` para dar una portada a cada evento. Las categorías vacías muestran un mensaje y se pueden seleccionar desde el desplegable. El registro público está disponible en `POST /api/registro/` y siempre crea espectadores sin privilegios de administración.

## Archivos de configuración

- `requirements.txt`: dependencias del proyecto.
- `.env.example`: ejemplo de configuración sin credenciales reales.
- `.env`: configuración privada local, excluida de Git.
- `env/`: entorno virtual local, excluido de Git.


## Registro y validaciones

La interfaz está en español. Se solicitan nombres, apellido paterno, email y contraseña; usuarios chilenos requieren RUT con dígito verificador válido. Extranjeros requieren un documento de 5–30 letras, números o guiones. RUT y documento extranjero se normalizan y no se repiten. Los correos se comparan sin distinguir mayúsculas. Los usuarios antiguos pueden seguir iniciando sesión con su username; las cuentas nuevas también ingresan mediante su email.

La contraseña tiene entre 8 y 16 caracteres, no admite espacios, requiere mayúscula, minúscula, número y al menos uno de `@ $ # *`. También se mantienen los validadores de Django contra contraseñas comunes o similares a los datos personales. Las contraseñas se guardan con el hash de Django; el hash rápido MD5 se activa únicamente dentro de las pruebas, nunca en el servidor normal.

La API impide fechas nuevas vencidas, precios negativos o con fracciones de peso, cantidades menores a 1 o mayores a 20 por sector, sectores agotados y cantidades acumuladas mayores al stock disponible. El checkout vuelve a verificar disponibilidad. El administrador valida fechas y precios antes de guardar; los pagos y reembolsos se muestran únicamente como auditoría de lectura.

El límite de intentos de registro/login ayuda a evitar abuso, pero el cache local y el servidor de desarrollo no sustituyen una configuración comercial de producción.


### Asientos y ciudades

Cada concierto dispone de un plano común con Cancha, Tribuna y VIP. Las sillas se seleccionan por fila y número, se guardan en el carro y aparecen en la entrada comprada. Una reserva de pago vigente bloquea esas sillas; la cancelación libera las entradas. La base de datos impide emitir dos entradas válidas para la misma silla.

`GET /api/eventos/{id}/asientos/` consulta el plano y su disponibilidad. El carro recibe `asientos` como lista de IDs, junto con el sector y una cantidad igual al número de sillas seleccionadas.

La cartelera incluye Santiago, Viña del Mar, Concepción, Valparaíso, Antofagasta, La Serena y Temuco. Para preparar los asientos y ciudades de la cartelera incluida, ejecuta `python manage.py configurar_recintos`. Repetir el comando conserva los IDs y el stock.

El retorno de Webpay redirige al inicio con un mensaje basado en el resultado verificado por el servidor. La autorización bancaria y las pantallas del proveedor pertenecen a Transbank; activar cobros comerciales requiere credenciales de producción.
