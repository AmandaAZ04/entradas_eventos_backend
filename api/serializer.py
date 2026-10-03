import re
import uuid

from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import (
    Asiento,
    Compra,
    DetalleCompra,
    Entrada,
    Evento,
    ItemCarro,
    Pago,
    Recinto,
    Sector,
    Usuario,
)
from .validators import normalizar_rut, validar_nombre
from .seating import validar_asientos


# El registro público crea espectadores y valida los datos también sin navegador.
class RegistroSerializer(serializers.ModelSerializer):
    nombres = serializers.CharField(
        source="first_name", max_length=150, validators=[validar_nombre]
    )
    apellido_paterno = serializers.CharField(
        source="last_name", max_length=150, validators=[validar_nombre]
    )
    email = serializers.EmailField(required=True, max_length=254)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    rut = serializers.CharField(
        required=False, allow_blank=True, max_length=20, write_only=True
    )
    documento_extranjero = serializers.CharField(
        required=False, allow_blank=True, max_length=30, write_only=True
    )
    username = serializers.CharField(required=False, max_length=150)

    class Meta:
        model = Usuario
        fields = [
            "id",
            "username",
            "nombres",
            "apellido_paterno",
            "email",
            "extranjero",
            "rut",
            "documento_extranjero",
            "password",
        ]
        read_only_fields = ["id"]

    def validate_email(self, value):
        value = value.strip().lower()
        if Usuario.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "Este correo ya tiene una cuenta. Inicia sesión."
            )
        return value

    def validate(self, attrs):
        attrs["first_name"] = validar_nombre(attrs["first_name"])
        attrs["last_name"] = validar_nombre(attrs["last_name"])
        if attrs.get("extranjero", False):
            documento = attrs.get("documento_extranjero", "").strip().upper()
            if not re.fullmatch(r"[A-Z0-9-]{5,30}", documento):
                raise serializers.ValidationError(
                    {
                        "documento_extranjero": "Ingresa un pasaporte o documento de 5 a 30 letras y números."
                    }
                )
            if Usuario.objects.filter(documento_extranjero=documento).exists():
                raise serializers.ValidationError(
                    {"documento_extranjero": "Este documento ya está registrado."}
                )
            attrs.update(rut=None, documento_extranjero=documento)
        else:
            from django.core.exceptions import ValidationError

            try:
                rut = normalizar_rut(attrs.get("rut", ""))
            except ValidationError as error:
                raise serializers.ValidationError({"rut": error.messages})
            if Usuario.objects.filter(rut=rut).exists():
                raise serializers.ValidationError(
                    {"rut": "Este RUT ya está registrado."}
                )
            attrs.update(rut=rut, documento_extranjero=None)
        # Construye un usuario temporal para detectar contraseñas parecidas a sus datos.
        usuario = Usuario(**{k: v for k, v in attrs.items() if k != "password"})
        from django.core.exceptions import ValidationError

        try:
            validate_password(attrs["password"], user=usuario)
        except ValidationError as error:
            raise serializers.ValidationError({"password": error.messages})
        return attrs

    def create(self, validated_data):
        validated_data.setdefault("username", f"fan_{uuid.uuid4().hex[:24]}")
        try:
            with transaction.atomic():
                return Usuario.objects.create_user(
                    rol=Usuario.Rol.ESPECTADOR, **validated_data
                )
        except IntegrityError:
            raise serializers.ValidationError(
                "El correo o documento ya está registrado."
            )


# Incluye el nombre de usuario y su rol en ambos tokens.
class LoginSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["username"] = user.username
        token["rol"] = user.rol
        return token

    # También muestra los datos básicos del usuario en la respuesta.
    def validate(self, attrs):
        identificador = attrs.get("username", "").strip()
        if "@" in identificador:
            usuario = Usuario.objects.filter(email__iexact=identificador).first()
            if usuario:
                attrs["username"] = usuario.username
        data = super().validate(attrs)
        data["usuario"] = {
            "id": self.user.pk,
            "username": self.user.username,
            "rol": self.user.rol,
            "nombres": self.user.first_name,
        }
        return data


# Conversión de recintos a JSON.
class RecintoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Recinto
        fields = ["id", "nombre", "direccion", "ciudad"]


# Valida los sectores y evita asociarlos a eventos ajenos.
class SectorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sector
        fields = ["id", "evento", "nombre", "precio", "stock"]

    def validate_evento(self, evento):
        usuario = self.context["request"].user

        if evento.organizador_id != usuario.pk:
            raise serializers.ValidationError(
                "Solo puedes gestionar sectores de tus eventos."
            )

        return evento

    def validate_precio(self, precio):
        if precio <= 0 or precio != precio.to_integral_value():
            raise serializers.ValidationError(
                "El precio debe ser positivo y expresarse en pesos enteros (CLP)."
            )

        return precio


# El organizador se asigna desde el usuario autenticado.
# El cliente no puede elegir otro organizador en el JSON.
class EventoSerializer(serializers.ModelSerializer):
    sectores = SectorSerializer(many=True, read_only=True)

    class Meta:
        model = Evento
        fields = [
            "id",
            "nombre",
            "artista",
            "descripcion",
            "fecha_hora",
            "activo",
            "recinto",
            "organizador",
            "sectores",
            "imagen_url",
            "es_demo",
            "categoria",
        ]
        read_only_fields = ["organizador"]

    def validate_fecha_hora(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError("La fecha del evento debe ser futura.")
        return value

    def validate_imagen_url(self, value):
        if value and not value.startswith("https://"):
            raise serializers.ValidationError(
                "La imagen debe usar una dirección HTTPS."
            )
        return value


# Valida el sector y la cantidad solicitada.
# El carro se asigna desde el usuario autenticado.
class ItemCarroSerializer(serializers.ModelSerializer):
    sector = serializers.PrimaryKeyRelatedField(
        queryset=Sector.objects.filter(evento__activo=True)
    )
    cantidad = serializers.IntegerField(min_value=1, max_value=20)
    asientos = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=20
    )
    asientos_etiquetas = serializers.SerializerMethodField()

    def get_asientos_etiquetas(self, obj) -> list[str]:
        return [
            a.etiqueta
            for a in Asiento.objects.filter(pk__in=obj.asientos).order_by(
                "fila", "numero"
            )
        ]

    def validate(self, attrs):
        validar_asientos(attrs["sector"], attrs.get("asientos", []), attrs["cantidad"])
        return attrs

    sector_nombre = serializers.CharField(
        source="sector.nombre",
        read_only=True,
    )
    evento_nombre = serializers.CharField(
        source="sector.evento.nombre",
        read_only=True,
    )
    precio_unitario = serializers.DecimalField(
        source="sector.precio",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = ItemCarro
        fields = [
            "id",
            "sector",
            "asientos",
            "asientos_etiquetas",
            "sector_nombre",
            "evento_nombre",
            "cantidad",
            "precio_unitario",
        ]
        read_only_fields = ["id"]

    def validate_sector(self, value):
        if value.evento.fecha_hora <= timezone.now():
            raise serializers.ValidationError("Este evento ya no está disponible.")
        if value.stock < 1:
            raise serializers.ValidationError("Este sector está agotado.")
        return value


# Información de cada ticket emitido.
class EntradaSerializer(serializers.ModelSerializer):
    es_demo = serializers.SerializerMethodField()

    def get_es_demo(self, obj) -> bool:
        compra = obj.detalle.compra
        return (
            obj.detalle.sector.evento.es_demo
            or not compra.pago_id
            or compra.pago.ambiente != "production"
        )

    asiento = serializers.CharField(
        source="asiento.etiqueta", read_only=True, default=""
    )

    evento = serializers.CharField(
        source="detalle.sector.evento.nombre",
        read_only=True,
    )
    sector = serializers.CharField(
        source="detalle.sector.nombre",
        read_only=True,
    )

    class Meta:
        model = Entrada
        fields = [
            "id",
            "codigo",
            "asiento",
            "es_demo",
            "evento",
            "sector",
            "valida",
            "utilizada",
            "emitida",
        ]
        read_only_fields = fields


# Detalle histórico de cantidades, precios y entradas.
class DetalleCompraSerializer(serializers.ModelSerializer):
    evento = serializers.CharField(source="sector.evento.nombre", read_only=True)
    entradas = EntradaSerializer(many=True, read_only=True)

    class Meta:
        model = DetalleCompra
        fields = [
            "id",
            "sector",
            "cantidad",
            "precio_unitario",
            "evento",
            "entradas",
        ]
        read_only_fields = fields


# Respuesta de la compra; el cliente no puede editar su estado.
class CompraSerializer(serializers.ModelSerializer):
    detalles = DetalleCompraSerializer(many=True, read_only=True)

    class Meta:
        model = Compra
        fields = ["id", "estado", "total", "creada", "detalles"]
        read_only_fields = fields


# Solo admite los estados que puede asignar el organizador.
class CambiarEstadoCompraSerializer(serializers.Serializer):
    estado = serializers.ChoiceField(
        choices=[
            Compra.Estado.CANCELADO,
            Compra.Estado.ENTREGADO,
        ]
    )


# Datos para redirigir al checkout alojado por Transbank, sin recibir tarjetas.
class PagoSerializer(serializers.ModelSerializer):
    compras = CompraSerializer(many=True, read_only=True)

    class Meta:
        model = Pago
        fields = ["id", "estado", "total", "url", "token", "ambiente", "compras"]
        read_only_fields = fields


# Mapa público: muestra números y disponibilidad, nunca datos de compradores.
class AsientoSerializer(serializers.ModelSerializer):
    disponible = serializers.SerializerMethodField()
    etiqueta = serializers.CharField(read_only=True)

    def get_disponible(self, obj) -> bool:
        return obj.pk not in self.context.get("ocupados", set())

    class Meta:
        model = Asiento
        fields = ["id", "fila", "numero", "etiqueta", "disponible"]


class MapaSectorSerializer(serializers.ModelSerializer):
    asientos = AsientoSerializer(many=True, read_only=True)

    class Meta:
        model = Sector
        fields = ["id", "nombre", "precio", "stock", "asientos"]
