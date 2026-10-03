from datetime import timedelta

from django.test import TestCase, TransactionTestCase, override_settings
from unittest.mock import MagicMock, patch
from decimal import Decimal
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from .models import (
    Asiento,
    Usuario,
    Recinto,
    Evento,
    Sector,
    Compra,
    Entrada,
    ItemCarro,
    Pago,
    DetalleCompra,
    Carro,
    Reembolso,
)


from .payments import confirmar_pago


# Cada prueba recibe datos independientes en una base de pruebas.
@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    WEBPAY_ENVIRONMENT="integration",
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication"
        ],
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
        "DEFAULT_FILTER_BACKENDS": [
            "django_filters.rest_framework.DjangoFilterBackend"
        ],
        "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    },
)
class FlujoEntradasTests(TestCase):
    # El formulario público no puede crear organizadores ni superusuarios.
    def test_registro_publico_sin_escalamiento_de_privilegios(self):
        respuesta = self.client.post(
            "/api/registro/",
            {
                "username": "nuevo_fan",
                "email": "fan@example.com",
                "nombres": "Ana",
                "apellido_paterno": "Pérez",
                "rut": "12.345.678-5",
                "password": "BuenaClave39@",
                "rol": "ORGANIZADOR",
                "is_staff": True,
                "is_superuser": True,
            },
            format="json",
        )
        self.assertEqual(respuesta.status_code, 201)
        usuario = Usuario.objects.get(username="nuevo_fan")
        self.assertEqual(usuario.rol, Usuario.Rol.ESPECTADOR)
        self.assertFalse(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)
        self.assertTrue(usuario.check_password("BuenaClave39@"))

    def test_registro_rechaza_password_debil(self):
        respuesta = self.client.post(
            "/api/registro/",
            {
                "username": "nuevo_fan",
                "email": "fan@example.com",
                "password": "123",
                "nombres": "Ana",
                "apellido_paterno": "Pérez",
                "rut": "123456785",
            },
            format="json",
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(Usuario.objects.filter(username="nuevo_fan").exists())

    def setUp(self):
        self.client = APIClient()
        self.gateway = MagicMock()
        self.gateway.create.side_effect = lambda *args: {
            "token": "a" * 64,
            "url": "https://webpay3gint.transbank.cl/webpayserver/initTransaction",
        }
        self.gateway.refund.return_value = {"type": "REVERSED"}
        self.addCleanup(patch.stopall)
        patch("api.payments.cliente_webpay", return_value=self.gateway).start()
        patch("api.services.cliente_webpay", return_value=self.gateway).start()
        patch(
            "rest_framework.throttling.ScopedRateThrottle.allow_request",
            return_value=True,
        ).start()

        self.espectador = Usuario.objects.create_user(
            username="espectador",
            password="ClavePrueba123!",
            rol=Usuario.Rol.ESPECTADOR,
        )
        self.otro_espectador = Usuario.objects.create_user(
            username="otro_espectador",
            password="ClavePrueba123!",
            rol=Usuario.Rol.ESPECTADOR,
        )
        self.organizador = Usuario.objects.create_user(
            username="organizador",
            password="ClavePrueba123!",
            rol=Usuario.Rol.ORGANIZADOR,
        )
        self.otro_organizador = Usuario.objects.create_user(
            username="otro_organizador",
            password="ClavePrueba123!",
            rol=Usuario.Rol.ORGANIZADOR,
        )

        recinto = Recinto.objects.create(
            nombre="Recinto de prueba",
            direccion="Calle 123",
            ciudad="Santiago",
        )
        evento = Evento.objects.create(
            nombre="Concierto de prueba",
            artista="Banda de prueba",
            fecha_hora=timezone.now() + timedelta(days=30),
            recinto=recinto,
            organizador=self.organizador,
        )
        self.sector = Sector.objects.create(
            evento=evento,
            nombre="Cancha",
            precio="30000.00",
            stock=10,
        )

    def agregar_al_carro(self, cantidad=2):
        self.client.force_authenticate(user=self.espectador)
        return self.client.post(
            "/api/carro-tickets/",
            {"sector": self.sector.pk, "cantidad": cantidad},
            format="json",
        )

    def comprar(self):
        self.agregar_al_carro()
        respuesta = self.client.post("/api/compras/pagar/")
        self.assertEqual(respuesta.status_code, 201)
        pago = Pago.objects.get(pk=respuesta.data["id"])
        self.autorizar(pago)
        confirmar_pago(pago.token)
        return respuesta.data["compras"][0]["id"]

    def autorizar(self, pago):
        self.gateway.status.return_value = {
            "status": "AUTHORIZED",
            "response_code": 0,
            "buy_order": pago.orden,
            "session_id": str(pago.usuario_id),
            "amount": int(pago.total),
            "authorization_code": "123456",
        }

    # Comprueba el login real y el claim de rol dentro del JWT.
    def test_login_incluye_rol(self):
        respuesta = self.client.post(
            "/api/token/",
            {
                "username": "espectador",
                "password": "ClavePrueba123!",
            },
            format="json",
        )

        self.assertEqual(respuesta.status_code, 200)
        token = AccessToken(respuesta.data["access"])
        self.assertEqual(token["rol"], "ESPECTADOR")

    def test_catalogo_publico_y_carro_protegido(self):
        self.assertEqual(
            self.client.get("/api/eventos/").status_code,
            200,
        )
        self.assertEqual(
            self.client.get("/api/carro-tickets/").status_code,
            401,
        )

    def test_espectador_no_crea_eventos(self):
        self.client.force_authenticate(user=self.espectador)
        respuesta = self.client.post("/api/eventos/", {}, format="json")
        self.assertEqual(respuesta.status_code, 403)

    # Agregar al carro conserva el stock y suma los duplicados.
    def test_carro_suma_cantidades_sin_descontar_stock(self):
        self.agregar_al_carro(2)
        self.agregar_al_carro(3)

        item = ItemCarro.objects.get(carro__usuario=self.espectador)
        self.sector.refresh_from_db()

        self.assertEqual(item.cantidad, 5)
        self.assertEqual(self.sector.stock, 10)

    def test_carro_persiste_y_es_privado(self):
        self.agregar_al_carro()
        item = ItemCarro.objects.get(carro__usuario=self.espectador)

        self.client.force_authenticate(user=None)
        self.client.force_authenticate(user=self.espectador)
        respuesta = self.client.get("/api/carro-tickets/")
        self.assertEqual(len(respuesta.data), 1)

        self.client.force_authenticate(user=self.otro_espectador)
        self.assertEqual(
            self.client.get("/api/carro-tickets/").data,
            [],
        )
        self.assertEqual(
            self.client.delete(f"/api/carro-tickets/{item.pk}/").status_code,
            404,
        )

    # Pago correcto: stock, total, UUID y vaciado del carro.
    def test_pago_emite_entradas_y_no_se_repite(self):
        compra_id = self.comprar()
        compra = Compra.objects.get(pk=compra_id)
        entradas = Entrada.objects.filter(detalle__compra=compra)

        self.sector.refresh_from_db()

        self.assertEqual(compra.estado, "PAGADO")
        self.assertEqual(compra.total, 60000)
        self.assertEqual(self.sector.stock, 8)
        self.assertEqual(entradas.count(), 2)
        self.assertEqual(
            len(set(entradas.values_list("codigo", flat=True))),
            2,
        )
        self.assertFalse(ItemCarro.objects.exists())

        respuesta = self.client.post("/api/compras/pagar/")
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(Compra.objects.count(), 1)

    def test_stock_insuficiente_conserva_carro(self):
        self.agregar_al_carro(10)
        self.sector.stock = 9
        self.sector.save(update_fields=["stock"])
        respuesta = self.client.post("/api/compras/pagar/")

        self.sector.refresh_from_db()

        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(self.sector.stock, 9)
        self.assertEqual(Compra.objects.count(), 0)
        self.assertEqual(Entrada.objects.count(), 0)
        self.assertTrue(ItemCarro.objects.exists())

    # Cancelar dos veces devuelve el stock una sola vez.
    def test_cancelacion_no_duplica_stock(self):
        compra_id = self.comprar()
        self.client.force_authenticate(user=self.organizador)
        ruta = f"/api/compras/{compra_id}/estado/"

        for _ in range(2):
            respuesta = self.client.patch(
                ruta,
                {"estado": "CANCELADO"},
                format="json",
            )
            self.assertEqual(respuesta.status_code, 200)

        self.sector.refresh_from_db()
        self.assertEqual(self.sector.stock, 10)
        self.assertFalse(Entrada.objects.filter(valida=True).exists())

    def test_otro_organizador_no_cancela_compra(self):
        compra_id = self.comprar()
        self.client.force_authenticate(user=self.otro_organizador)
        respuesta = self.client.patch(
            f"/api/compras/{compra_id}/estado/",
            {"estado": "CANCELADO"},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 404)

    def test_entrega_marca_ingreso_y_no_permite_cancelar(self):
        compra_id = self.comprar()
        self.client.force_authenticate(user=self.organizador)
        ruta = f"/api/compras/{compra_id}/estado/"

        respuesta = self.client.patch(
            ruta,
            {"estado": "ENTREGADO"},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Entrada.objects.filter(utilizada=False).exists())

        respuesta = self.client.patch(
            ruta,
            {"estado": "CANCELADO"},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 400)

        self.sector.refresh_from_db()
        self.assertEqual(self.sector.stock, 8)

    def registro(self, **changes):
        datos = {
            "nombres": "Ana María",
            "apellido_paterno": "Pérez",
            "email": "ana@example.com",
            "rut": "12345678-5",
            "password": "BuenaClave39@",
        }
        datos.update(changes)
        return self.client.post("/api/registro/", datos, format="json")

    def test_registro_normaliza_rut_email_y_login_por_email(self):
        self.assertEqual(
            self.registro(email="ANA@EXAMPLE.COM", rut="12.345.678-5").status_code, 201
        )
        usuario = Usuario.objects.get(email="ana@example.com")
        self.assertEqual(usuario.rut, "12345678-5")
        respuesta = self.client.post(
            "/api/token/",
            {"username": "ANA@EXAMPLE.COM", "password": "BuenaClave39@"},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["usuario"]["nombres"], "Ana María")
        self.assertEqual(self.registro(email="ANA@EXAMPLE.COM").status_code, 400)
        self.assertEqual(
            self.registro(email="otro@example.com", rut="123456785").status_code, 400
        )

    def test_registro_rut_incorrecto_y_nombres_invalidos(self):
        for cambios in [
            {"rut": "12345678-9"},
            {"rut": ""},
            {"nombres": "Ana123"},
            {"apellido_paterno": "<script>"},
        ]:
            with self.subTest(cambios=cambios):
                self.assertEqual(self.registro(**cambios).status_code, 400)
        self.assertFalse(Usuario.objects.filter(email="ana@example.com").exists())

    def test_registro_extranjero_exige_documento(self):
        self.assertEqual(
            self.registro(extranjero=True, rut="", documento_extranjero="").status_code,
            400,
        )
        self.assertEqual(
            self.registro(
                extranjero=True, rut="", documento_extranjero="ab12345"
            ).status_code,
            201,
        )
        usuario = Usuario.objects.get(email="ana@example.com")
        self.assertIsNone(usuario.rut)
        self.assertEqual(usuario.documento_extranjero, "AB12345")
        self.assertEqual(
            self.registro(
                email="otra@example.com",
                extranjero=True,
                documento_extranjero="AB12345",
            ).status_code,
            400,
        )

    def test_todas_las_reglas_de_password(self):
        for password in [
            "Aa1@",
            "UnaClaveDemasiadoLarga123@",
            "Buena Clave39@",
            "buenaclave39@",
            "BUENACLAVE39@",
            "BuenaClave39!",
            "BuenaClave@",
        ]:
            with self.subTest(password=password):
                respuesta = self.registro(password=password)
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn("password", respuesta.data)

    def test_cantidad_stock_fecha_y_precios_validos(self):
        for cantidad in [0, -1, 1.5, 21, 11]:
            self.assertEqual(self.agregar_al_carro(cantidad).status_code, 400)
        self.agregar_al_carro(6)
        self.assertEqual(self.agregar_al_carro(5).status_code, 400)
        self.sector.evento.fecha_hora = timezone.now() - timedelta(days=1)
        self.sector.evento.save()
        self.assertEqual(self.agregar_al_carro(1).status_code, 400)
        self.client.force_authenticate(self.organizador)
        self.assertEqual(
            self.client.post(
                "/api/sectores/",
                {
                    "evento": self.sector.evento_id,
                    "nombre": "VIP",
                    "precio": "123.50",
                    "stock": 2,
                },
                format="json",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/eventos/",
                {
                    "nombre": "Evento",
                    "artista": "Banda",
                    "recinto": self.sector.evento.recinto_id,
                    "fecha_hora": (timezone.now() - timedelta(days=1)).isoformat(),
                },
                format="json",
            ).status_code,
            400,
        )

    def test_filtros_de_categoria_artista_ciudad_fecha_y_precio(self):
        evento = self.sector.evento
        evento.categoria = "KPOP"
        evento.save()
        self.assertEqual(
            len(
                self.client.get(
                    "/api/eventos/?categoria=KPOP&artista=Banda&ciudad=Santiago"
                ).data
            ),
            1,
        )
        self.assertEqual(self.client.get("/api/eventos/?categoria=ROCK").data, [])
        self.assertEqual(
            self.client.get(
                "/api/eventos/",
                {"fecha_desde": (timezone.now() + timedelta(days=31)).isoformat()},
            ).data,
            [],
        )
        self.assertEqual(self.client.get("/api/sectores/?precio_min=40000").data, [])
        self.assertEqual(
            len(self.client.get("/api/sectores/?precio_max=30000&stock_min=5").data), 1
        )

    def iniciar(self):
        self.agregar_al_carro()
        respuesta = self.client.post("/api/compras/pagar/")
        self.assertEqual(respuesta.status_code, 201)
        return Pago.objects.get(pk=respuesta.data["id"])

    def test_webpay_pendiente_no_emite_ni_descuenta_y_reintento_reutiliza(self):
        pago = self.iniciar()
        self.assertEqual(pago.compras.first().estado, "PENDIENTE")
        self.assertFalse(Entrada.objects.exists())
        self.sector.refresh_from_db()
        self.assertEqual(self.sector.stock, 10)
        respuesta = self.client.post("/api/compras/pagar/")
        self.assertEqual(str(pago.pk), respuesta.data["id"])
        self.gateway.create.assert_called_once()

    def test_confirmacion_repetida_no_duplica_tickets(self):
        pago = self.iniciar()
        self.autorizar(pago)
        for _ in range(2):
            confirmar_pago(pago.token)
        self.sector.refresh_from_db()
        self.assertEqual(self.sector.stock, 8)
        self.assertEqual(Entrada.objects.count(), 2)
        self.gateway.status.assert_called_once()

    def test_pago_rechazado_no_modifica_stock(self):
        pago = self.iniciar()
        self.autorizar(pago)
        self.gateway.status.return_value.update(status="FAILED", response_code=-1)
        confirmar_pago(pago.token)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, "RECHAZADO")
        self.assertEqual(pago.compras.first().estado, "CANCELADO")
        self.sector.refresh_from_db()
        self.assertEqual(self.sector.stock, 10)
        self.assertFalse(Entrada.objects.exists())

    def test_total_u_orden_manipulado_no_emite_entradas(self):
        pago = self.iniciar()
        self.autorizar(pago)
        self.gateway.status.return_value["amount"] = 1
        confirmar_pago(pago.token)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, "REVISION")
        self.assertFalse(Entrada.objects.exists())

    def test_fallo_proveedor_conserva_carro(self):
        self.agregar_al_carro()
        self.gateway.create.side_effect = TimeoutError()
        self.assertEqual(self.client.post("/api/compras/pagar/").status_code, 400)
        self.assertTrue(ItemCarro.objects.exists())
        self.assertFalse(Pago.objects.exists())

    def test_reserva_evitar_sobreventa_sin_descontar_stock(self):
        self.sector.stock = 2
        self.sector.save()
        self.iniciar()
        self.client.force_authenticate(self.otro_espectador)
        self.client.post(
            "/api/carro-tickets/",
            {"sector": self.sector.pk, "cantidad": 1},
            format="json",
        )
        self.assertEqual(self.client.post("/api/compras/pagar/").status_code, 400)
        self.sector.refresh_from_db()
        self.assertEqual(self.sector.stock, 2)

    def test_stock_cambiado_devuelve_pago_sin_tickets(self):
        pago = self.iniciar()
        self.autorizar(pago)
        self.sector.stock = 0
        self.sector.save()
        confirmar_pago(pago.token)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, "REEMBOLSADO")
        self.assertFalse(Entrada.objects.exists())
        self.gateway.refund.assert_called_once_with(pago.token, 60000)

    def test_devolucion_incierta_no_duplica_dinero_ni_stock(self):
        compra_id = self.comprar()
        self.gateway.refund.side_effect = TimeoutError()
        self.client.force_authenticate(self.organizador)
        for _ in range(2):
            self.assertEqual(
                self.client.patch(
                    f"/api/compras/{compra_id}/estado/",
                    {"estado": "CANCELADO"},
                    format="json",
                ).status_code,
                400,
            )
        self.gateway.refund.assert_called_once()
        self.sector.refresh_from_db()
        self.assertEqual(self.sector.stock, 8)
        self.assertEqual(Compra.objects.get(pk=compra_id).estado, "PAGADO")
        self.assertEqual(Reembolso.objects.get(compra_id=compra_id).estado, "REVISION")

    @override_settings(
        WEBPAY_ENVIRONMENT="production",
        WEBPAY_RETURN_URL="https://example.com/pago/retorno/",
    )
    def test_produccion_no_cobra_conciertos_ficticios(self):
        evento = self.sector.evento
        evento.es_demo = True
        evento.save()
        self.agregar_al_carro()
        self.assertEqual(self.client.post("/api/compras/pagar/").status_code, 400)
        self.gateway.create.assert_not_called()

    def test_callback_desconocido_y_aborto_no_autorizan(self):
        self.assertEqual(
            self.client.get("/pago/retorno/?token_ws=inventado").status_code, 302
        )
        self.assertFalse(Entrada.objects.exists())
        pago = self.iniciar()
        self.autorizar(pago)
        self.gateway.status.return_value.update(
            status="INITIALIZED", response_code=None
        )
        self.client.post("/pago/retorno/", {"TBK_TOKEN": pago.token})
        self.gateway.commit.assert_not_called()
        self.assertFalse(Entrada.objects.exists())
        pago.refresh_from_db()
        self.assertEqual(pago.estado, "CANCELADO")

    def datos_evento_panel(self):
        return {
            "nombre": "Show del panel",
            "artista": "Banda del panel",
            "fecha_hora": (timezone.now() + timedelta(days=45)).isoformat(),
            "recinto": self.sector.evento.recinto_id,
            "categoria": "POP",
            "sectores": [
                {"nombre": "Cancha general", "precio": 35000, "stock": 12},
                {"nombre": "VIP", "precio": 85000, "stock": 5},
            ],
        }

    def test_panel_alta_completa_y_compra_de_asiento_nuevo(self):
        self.client.force_authenticate(self.organizador)
        respuesta = self.client.post(
            "/api/eventos/crear-completo/", self.datos_evento_panel(), format="json"
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        evento = Evento.objects.get(pk=respuesta.data["id"])
        self.assertEqual(evento.organizador_id, self.organizador.pk)
        self.assertEqual(evento.sectores.count(), 2)
        sector = evento.sectores.get(nombre="Cancha general")
        self.assertEqual(sector.asientos.count(), 12)
        self.assertEqual(sector.asientos.last().etiqueta, "B-02")
        self.client.force_authenticate(self.espectador)
        silla = sector.asientos.first()
        respuesta = self.client.post(
            "/api/carro-tickets/",
            {"sector": sector.pk, "cantidad": 1, "asientos": [silla.pk]},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 201)
        respuesta = self.client.post("/api/compras/pagar/")
        self.assertEqual(respuesta.status_code, 201)
        pago = Pago.objects.get(pk=respuesta.data["id"])
        self.autorizar(pago)
        confirmar_pago(pago.token)
        self.assertEqual(Entrada.objects.get().asiento_id, silla.pk)
        sector.refresh_from_db()
        self.assertEqual(sector.stock, 11)

    def test_panel_alta_invalida_no_deja_evento_ni_sillas(self):
        self.client.force_authenticate(self.organizador)
        datos = self.datos_evento_panel()
        datos["sectores"][1]["precio"] = -1
        self.assertEqual(
            self.client.post(
                "/api/eventos/crear-completo/", datos, format="json"
            ).status_code,
            400,
        )
        self.assertFalse(Evento.objects.filter(nombre=datos["nombre"]).exists())
        self.assertFalse(Asiento.objects.exists())
        datos["sectores"][1].update(nombre="cancha GENERAL", precio=85000)
        self.assertEqual(
            self.client.post(
                "/api/eventos/crear-completo/", datos, format="json"
            ).status_code,
            400,
        )
        self.assertFalse(Evento.objects.filter(nombre=datos["nombre"]).exists())

    def test_panel_espectador_y_anonimo_no_acceden_ni_publican(self):
        for usuario in [None, self.espectador]:
            self.client.force_authenticate(usuario)
            self.assertIn(
                self.client.get("/api/eventos/mis-eventos/").status_code, [401, 403]
            )
            self.assertIn(
                self.client.post(
                    "/api/eventos/crear-completo/",
                    self.datos_evento_panel(),
                    format="json",
                ).status_code,
                [401, 403],
            )

    def test_panel_mis_eventos_solo_propios_y_actualizacion_protegida(self):
        self.client.force_authenticate(self.otro_organizador)
        respuesta = self.client.post(
            "/api/eventos/crear-completo/", self.datos_evento_panel(), format="json"
        )
        nuevo = respuesta.data["id"]
        respuesta = self.client.get("/api/eventos/mis-eventos/")
        self.assertEqual([e["id"] for e in respuesta.data], [nuevo])
        self.assertEqual(
            self.client.patch(
                f"/api/eventos/{self.sector.evento_id}/",
                {"nombre": "Ajeno"},
                format="json",
            ).status_code,
            403,
        )
        self.client.force_authenticate(self.organizador)
        self.assertEqual(self.client.delete(f"/api/eventos/{nuevo}/").status_code, 403)
        self.assertEqual(
            self.client.patch(
                f"/api/eventos/{self.sector.evento_id}/",
                {"nombre": "Nombre actualizado"},
                format="json",
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.delete(f"/api/eventos/{self.sector.evento_id}/").status_code,
            204,
        )
        self.sector.evento.refresh_from_db()
        self.assertFalse(self.sector.evento.activo)
        self.assertEqual(
            self.client.get(f"/api/eventos/{self.sector.evento_id}/").status_code, 200
        )
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.get(f"/api/eventos/{self.sector.evento_id}/").status_code, 404
        )

    def test_panel_recinto_y_sector_generan_asientos_con_permisos(self):
        self.client.force_authenticate(self.espectador)
        self.assertEqual(
            self.client.post(
                "/api/recintos/",
                {"nombre": "Nuevo", "ciudad": "Temuco", "direccion": "Calle 10"},
                format="json",
            ).status_code,
            403,
        )
        self.client.force_authenticate(self.organizador)
        self.assertEqual(
            self.client.post(
                "/api/recintos/",
                {"nombre": "Nuevo", "ciudad": "Temuco", "direccion": "Calle 10"},
                format="json",
            ).status_code,
            201,
        )
        datos = {
            "evento": self.sector.evento_id,
            "nombre": "Nueva localidad",
            "precio": 40000,
            "stock": 21,
        }
        respuesta = self.client.post("/api/sectores/", datos, format="json")
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(
            Asiento.objects.filter(sector_id=respuesta.data["id"]).count(), 21
        )
        self.client.force_authenticate(self.otro_organizador)
        datos["nombre"] = "Localidad ajena"
        self.assertEqual(
            self.client.post("/api/sectores/", datos, format="json").status_code, 400
        )

    def test_paginas_inexistentes_vuelven_al_inicio_con_y_sin_debug(self):
        for debug in [True, False]:
            with self.subTest(debug=debug), override_settings(DEBUG=debug):
                for ruta in ["/seccion/", "/seccion", "/otra/pagina/?dato=ejemplo"]:
                    self.assertRedirects(self.client.get(ruta), "/", status_code=302)
                self.assertEqual(self.client.head("/seccion/").status_code, 302)
                self.assertEqual(self.client.post("/seccion/", {}).status_code, 405)

    def test_redireccion_no_oculta_errores_api_ni_interfiere_rutas_reales(self):
        for ruta in [
            "/api/ruta-inexistente/",
            "/api/eventos/9999999/",
            "/static/archivo-inexistente.css",
            "/media/no-existe.jpg",
        ]:
            respuesta = self.client.get(ruta)
            self.assertEqual(respuesta.status_code, 404)
            self.assertNotIn("Location", respuesta.headers)
        self.assertEqual(self.client.get("/api/eventos/").status_code, 200)
        self.assertEqual(self.client.get("/api/docs/").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_schema_y_footer(self):
        self.assertEqual(self.client.get("/api/docs/").status_code, 200)
        respuesta = self.client.get(
            "/api/schema/", HTTP_ACCEPT="application/vnd.oai.openapi+json"
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("/api/compras/pagar/", respuesta.data["paths"])
        pagina = self.client.get("/")
        self.assertContains(pagina, "Amanda Angélica Álvarez Álvarez")
        self.assertContains(pagina, "IEC-N4-C1")

    def test_retorno_confirma_con_commit_y_reconciliacion_no_inicia_pago(self):
        pago = self.iniciar()
        self.autorizar(pago)
        aprobado = self.gateway.status.return_value.copy()
        self.gateway.status.return_value.update(
            status="INITIALIZED", response_code=None
        )
        confirmar_pago(pago.token, confirmar=False)
        self.gateway.commit.assert_not_called()
        self.assertFalse(Entrada.objects.exists())
        self.gateway.commit.return_value = aprobado
        self.client.get("/pago/retorno/", {"token_ws": pago.token})
        self.gateway.commit.assert_called_once_with(pago.token)
        self.assertEqual(Entrada.objects.count(), 2)

    def test_carro_multi_evento_congela_precio_y_agrupa_compras(self):
        evento = Evento.objects.create(
            nombre="Segundo evento",
            artista="Otro artista",
            fecha_hora=timezone.now() + timedelta(days=40),
            recinto=self.sector.evento.recinto,
            organizador=self.otro_organizador,
        )
        segundo = Sector.objects.create(
            evento=evento, nombre="VIP", precio=45000, stock=5
        )
        self.agregar_al_carro(2)
        self.client.post(
            "/api/carro-tickets/", {"sector": segundo.pk, "cantidad": 1}, format="json"
        )
        pago = Pago.objects.get(pk=self.client.post("/api/compras/pagar/").data["id"])
        self.assertEqual(pago.total, 105000)
        self.assertEqual(pago.compras.count(), 2)
        self.sector.precio = 50000
        self.sector.save()
        self.autorizar(pago)
        confirmar_pago(pago.token)
        self.assertEqual(Entrada.objects.count(), 3)
        self.assertEqual(pago.compras.get(detalles__sector=self.sector).total, 60000)
        self.client.force_authenticate(self.organizador)
        self.assertEqual(len(self.client.get("/api/compras/").data), 1)

    def test_carro_en_otro_cliente_y_refresh_con_claim_rol(self):
        self.agregar_al_carro()
        cliente = APIClient()
        login = cliente.post(
            "/api/token/",
            {"username": "espectador", "password": "ClavePrueba123!"},
            format="json",
        ).data
        refresh = cliente.post(
            "/api/token/refresh/", {"refresh": login["refresh"]}, format="json"
        )
        self.assertEqual(refresh.status_code, 200)
        self.assertEqual(AccessToken(refresh.data["access"])["rol"], "ESPECTADOR")
        cliente.credentials(HTTP_AUTHORIZATION="Bearer " + refresh.data["access"])
        self.assertEqual(len(cliente.get("/api/carro-tickets/").data), 1)
        self.client.force_authenticate(self.otro_espectador)
        self.assertEqual(self.client.get("/api/compras/").data, [])
        self.assertEqual(self.client.get("/api/mis-entradas/").data, [])

    def test_inicio_webpay_reintenta_conexion_y_crea_una_sola_reserva(self):
        from requests.exceptions import ConnectionError

        self.agregar_al_carro()
        self.gateway.create.side_effect = [
            ConnectionError(),
            {
                "token": "b" * 64,
                "url": "https://webpay3gint.transbank.cl/webpayserver/initTransaction",
            },
        ]
        respuesta = self.client.post("/api/compras/pagar/")
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(self.gateway.create.call_count, 2)
        self.assertEqual(
            self.gateway.create.call_args_list[0], self.gateway.create.call_args_list[1]
        )
        self.assertEqual(Pago.objects.count(), 1)
        self.assertEqual(Compra.objects.count(), 1)
        self.assertFalse(ItemCarro.objects.exists())
        self.assertFalse(Entrada.objects.exists())
        self.sector.refresh_from_db()
        self.assertEqual(self.sector.stock, 10)

    def test_inicio_webpay_timeout_conserva_carro_y_no_deja_reserva(self):
        from requests.exceptions import Timeout

        self.agregar_al_carro()
        self.gateway.create.side_effect = Timeout()
        respuesta = self.client.post("/api/compras/pagar/")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("tardó demasiado", str(respuesta.data))
        self.assertEqual(self.gateway.create.call_count, 2)
        self.assertFalse(Pago.objects.exists())
        self.assertFalse(Compra.objects.exists())
        self.assertTrue(ItemCarro.objects.exists())

    def test_inicio_webpay_no_reintenta_credenciales_invalidas(self):
        from transbank.error.transbank_error import TransbankError

        self.agregar_al_carro()
        self.gateway.create.side_effect = TransbankError("credenciales", 401)
        respuesta = self.client.post("/api/compras/pagar/")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("configuración del comercio", str(respuesta.data))
        self.gateway.create.assert_called_once()
        self.assertTrue(ItemCarro.objects.exists())
        self.assertFalse(Pago.objects.exists())

    def test_confirmacion_timeout_conserva_pendiente_sin_tickets(self):
        from rest_framework.exceptions import ValidationError

        pago = self.iniciar()
        self.gateway.status.side_effect = TimeoutError()
        with self.assertRaises(ValidationError):
            confirmar_pago(pago.token)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, "PENDIENTE")
        self.assertFalse(Entrada.objects.exists())

    def test_organizador_no_modifica_evento_ajeno_ni_paga(self):
        self.client.force_authenticate(self.otro_organizador)
        self.assertEqual(
            self.client.patch(
                f"/api/eventos/{self.sector.evento_id}/",
                {"nombre": "Ajeno"},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(self.client.post("/api/compras/pagar/").status_code, 403)

    def test_modelos_admin_validan_fecha_y_precio(self):
        from django.core.exceptions import ValidationError

        self.sector.precio = Decimal("123.50")
        with self.assertRaises(ValidationError):
            self.sector.full_clean()
        evento = self.sector.evento
        evento.fecha_hora = timezone.now() - timedelta(days=1)
        with self.assertRaises(ValidationError):
            evento.full_clean()

    def sillas(self):
        return [
            Asiento.objects.create(sector=self.sector, fila="A", numero=i)
            for i in range(1, 11)
        ]

    def seleccion(self, ids, usuario=None, cantidad=None, sector=None):
        self.client.force_authenticate(usuario or self.espectador)
        return self.client.post(
            "/api/carro-tickets/",
            {
                "sector": sector or self.sector.pk,
                "cantidad": len(ids) if cantidad is None else cantidad,
                "asientos": ids,
            },
            format="json",
        )

    def test_mapa_y_carro_con_asientos_numerados(self):
        sillas = self.sillas()
        self.assertEqual(self.seleccion([sillas[0].pk, sillas[1].pk]).status_code, 201)
        item = ItemCarro.objects.get()
        self.assertEqual(item.asientos, [sillas[0].pk, sillas[1].pk])
        self.assertEqual(
            self.client.get("/api/carro-tickets/").data[0]["asientos_etiquetas"],
            ["A-01", "A-02"],
        )
        self.assertEqual(self.seleccion([sillas[0].pk]).status_code, 400)
        self.assertEqual(self.seleccion([sillas[2].pk]).status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.cantidad, 3)
        self.assertEqual(self.sector.stock, 10)

    def test_asientos_rechazan_duplicados_cantidad_e_id_ajeno(self):
        sillas = self.sillas()
        for ids, cantidad in [
            ([sillas[0].pk, sillas[0].pk], 2),
            ([sillas[0].pk], 2),
            ([999999], 1),
            ([], 1),
        ]:
            with self.subTest(ids=ids):
                self.assertEqual(
                    self.seleccion(ids, cantidad=cantidad).status_code, 400
                )
        otra = Sector.objects.create(
            evento=self.sector.evento, nombre="Otra zona", precio=40000, stock=1
        )
        silla = Asiento.objects.create(sector=otra, fila="B", numero=1)
        self.assertEqual(self.seleccion([silla.pk]).status_code, 400)
        self.assertFalse(ItemCarro.objects.exists())

    def test_misma_silla_no_se_reserva_para_dos_compradores(self):
        silla = self.sillas()[0]
        self.assertEqual(self.seleccion([silla.pk]).status_code, 201)
        self.assertEqual(
            self.seleccion([silla.pk], usuario=self.otro_espectador).status_code, 201
        )
        self.client.force_authenticate(self.espectador)
        pago = Pago.objects.get(pk=self.client.post("/api/compras/pagar/").data["id"])
        mapa = self.client.get(f"/api/eventos/{self.sector.evento_id}/asientos/").data
        self.assertFalse(mapa[0]["asientos"][0]["disponible"])
        self.client.force_authenticate(self.otro_espectador)
        self.assertEqual(self.client.post("/api/compras/pagar/").status_code, 400)
        self.autorizar(pago)
        confirmar_pago(pago.token)
        self.assertEqual(Entrada.objects.get().asiento_id, silla.pk)
        self.sector.refresh_from_db()
        self.assertEqual(self.sector.stock, 9)
        self.assertEqual(
            self.seleccion([silla.pk], usuario=self.otro_espectador).status_code, 400
        )

    def test_cancelacion_libera_silla_y_conserva_ticket_historico(self):
        silla = self.sillas()[0]
        self.seleccion([silla.pk])
        pago = Pago.objects.get(pk=self.client.post("/api/compras/pagar/").data["id"])
        self.autorizar(pago)
        confirmar_pago(pago.token)
        compra = pago.compras.get()
        self.client.force_authenticate(self.organizador)
        self.assertEqual(
            self.client.patch(
                f"/api/compras/{compra.pk}/estado/",
                {"estado": "CANCELADO"},
                format="json",
            ).status_code,
            200,
        )
        self.assertFalse(Entrada.objects.get().valida)
        self.assertTrue(
            self.client.get(f"/api/eventos/{self.sector.evento_id}/asientos/").data[0][
                "asientos"
            ][0]["disponible"]
        )
        self.assertEqual(
            self.seleccion([silla.pk], usuario=self.otro_espectador).status_code, 201
        )

    def test_pago_numerado_vuelve_a_main_y_muestra_estado_verificado(self):
        silla = self.sillas()[0]
        self.seleccion([silla.pk])
        pago = Pago.objects.get(pk=self.client.post("/api/compras/pagar/").data["id"])
        self.autorizar(pago)
        respuesta = self.client.get(
            "/pago/retorno/", {"token_ws": pago.token}, follow=True
        )
        self.assertEqual(respuesta.redirect_chain[0][0], "/")
        self.assertContains(respuesta, "Pago aprobado!")
        ticket = self.client.get("/api/mis-entradas/").data[0]
        self.assertEqual(ticket["asiento"], "A-01")
        self.assertNotContains(self.client.get("/"), "Pago aprobado!")

    def test_rut_formato_normalizado_y_numero_antiguo_valido(self):
        from .validators import normalizar_rut

        self.assertEqual(normalizar_rut("12.345.678-5"), "12345678-5")
        self.assertEqual(normalizar_rut("123456785"), "12345678-5")
        self.assertEqual(normalizar_rut("1-9"), "1-9")


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    WEBPAY_ENVIRONMENT="integration",
)
class ConcurrenciaPagoTests(TransactionTestCase):
    """Dos conexiones PostgreSQL disputan el último ticket y repiten un retorno."""

    def test_ultimo_ticket_y_confirmaciones_simultaneas(self):
        import uuid
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections, close_old_connections
        from rest_framework.exceptions import ValidationError
        from .payments import iniciar_pago

        organizador = Usuario.objects.create_user(
            username="organizador_concurrente", rol="ORGANIZADOR"
        )
        recinto = Recinto.objects.create(
            nombre="Arena", direccion="Calle 1", ciudad="Santiago"
        )
        evento = Evento.objects.create(
            nombre="Último ticket",
            artista="Banda",
            fecha_hora=timezone.now() + timedelta(days=30),
            organizador=organizador,
            recinto=recinto,
        )
        sector = Sector.objects.create(
            evento=evento, nombre="General", precio=35000, stock=1
        )
        usuarios = [
            Usuario.objects.create_user(username=f"comprador_concurrente_{i}")
            for i in range(2)
        ]
        for usuario in usuarios:
            ItemCarro.objects.create(
                carro=Carro.objects.create(usuario=usuario), sector=sector, cantidad=1
            )
        gateway = MagicMock()
        gateway.create.side_effect = lambda *args: {
            "token": uuid.uuid4().hex + uuid.uuid4().hex,
            "url": "https://webpay3gint.transbank.cl/webpayserver/initTransaction",
        }
        barrera = Barrier(2)

        def checkout(usuario):
            close_old_connections()
            try:
                barrera.wait(timeout=10)
                try:
                    return iniciar_pago(usuario, "http://localhost/pago/retorno/").pk
                except ValidationError:
                    return None
            finally:
                connections.close_all()

        with patch("api.payments.cliente_webpay", return_value=gateway):
            with ThreadPoolExecutor(max_workers=2) as pool:
                resultados = list(pool.map(checkout, usuarios))
            self.assertEqual(sum(r is not None for r in resultados), 1)
            self.assertEqual(Pago.objects.count(), 1)
            sector.refresh_from_db()
            self.assertEqual(sector.stock, 1)
            self.assertEqual(ItemCarro.objects.count(), 1)
            pago = Pago.objects.get()
            gateway.status.return_value = {
                "status": "AUTHORIZED",
                "response_code": 0,
                "buy_order": pago.orden,
                "session_id": str(pago.usuario_id),
                "amount": 35000,
                "authorization_code": "123456",
            }
            barrera = Barrier(2)

            def retorno(_):
                close_old_connections()
                try:
                    barrera.wait(timeout=10)
                    return confirmar_pago(pago.token).estado
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(
                    list(pool.map(retorno, range(2))), ["AUTORIZADO", "AUTORIZADO"]
                )
        sector.refresh_from_db()
        self.assertEqual(sector.stock, 0)
        self.assertEqual(Entrada.objects.count(), 1)
        gateway.status.assert_called_once()
