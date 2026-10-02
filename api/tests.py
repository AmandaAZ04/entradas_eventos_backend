from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from .models import (
    Usuario,
    Recinto,
    Evento,
    Sector,
    Compra,
    Entrada,
    ItemCarro,
)


# Cada prueba recibe datos independientes en una base de pruebas.
class FlujoEntradasTests(TestCase):
    # El formulario público no puede crear organizadores ni superusuarios.
    def test_registro_publico_sin_escalamiento_de_privilegios(self):
        respuesta = self.client.post(
            "/api/registro/",
            {"username": "nuevo_fan", "email": "fan@example.com",
             "password": "UnaClaveDePrueba839!", "rol": "ORGANIZADOR",
             "is_staff": True, "is_superuser": True},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 201)
        usuario = Usuario.objects.get(username="nuevo_fan")
        self.assertEqual(usuario.rol, Usuario.Rol.ESPECTADOR)
        self.assertFalse(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)
        self.assertTrue(usuario.check_password("UnaClaveDePrueba839!"))

    def test_registro_rechaza_password_debil(self):
        respuesta = self.client.post(
            "/api/registro/",
            {"username": "nuevo_fan", "email": "fan@example.com",
             "password": "123"}, format="json",
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(Usuario.objects.filter(username="nuevo_fan").exists())

    def setUp(self):
        self.client = APIClient()

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
        return respuesta.data[0]["id"]

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
        respuesta = self.client.post(
            "/api/eventos/", {}, format="json"
        )
        self.assertEqual(respuesta.status_code, 403)

    # Agregar al carro conserva el stock y suma los duplicados.
    def test_carro_suma_cantidades_sin_descontar_stock(self):
        self.agregar_al_carro(2)
        self.agregar_al_carro(3)

        item = ItemCarro.objects.get(
            carro__usuario=self.espectador
        )
        self.sector.refresh_from_db()

        self.assertEqual(item.cantidad, 5)
        self.assertEqual(self.sector.stock, 10)

    def test_carro_persiste_y_es_privado(self):
        self.agregar_al_carro()
        item = ItemCarro.objects.get(
            carro__usuario=self.espectador
        )

        self.client.force_authenticate(user=None)
        self.client.force_authenticate(user=self.espectador)
        respuesta = self.client.get("/api/carro-tickets/")
        self.assertEqual(len(respuesta.data), 1)

        self.client.force_authenticate(
            user=self.otro_espectador
        )
        self.assertEqual(
            self.client.get("/api/carro-tickets/").data,
            [],
        )
        self.assertEqual(
            self.client.delete(
                f"/api/carro-tickets/{item.pk}/"
            ).status_code,
            404,
        )

    # Pago correcto: stock, total, UUID y vaciado del carro.
    def test_pago_emite_entradas_y_no_se_repite(self):
        compra_id = self.comprar()
        compra = Compra.objects.get(pk=compra_id)
        entradas = Entrada.objects.filter(
            detalle__compra=compra
        )

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
        self.agregar_al_carro(11)
        respuesta = self.client.post("/api/compras/pagar/")

        self.sector.refresh_from_db()

        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(self.sector.stock, 10)
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
        self.assertFalse(
            Entrada.objects.filter(valida=True).exists()
        )

    def test_otro_organizador_no_cancela_compra(self):
        compra_id = self.comprar()
        self.client.force_authenticate(
            user=self.otro_organizador
        )
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
        self.assertFalse(
            Entrada.objects.filter(utilizada=False).exists()
        )

        respuesta = self.client.patch(
            ruta,
            {"estado": "CANCELADO"},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 400)

        self.sector.refresh_from_db()
        self.assertEqual(self.sector.stock, 8)
