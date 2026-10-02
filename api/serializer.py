from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework import serializers
from .models import Recinto, Evento, Sector
from .models import ItemCarro

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
        data = super().validate(attrs)
        data["usuario"] = {
            "id": self.user.pk,
            "username": self.user.username,
            "rol": self.user.rol,
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
        if precio <= 0:
            raise serializers.ValidationError(
                "El precio debe ser mayor que cero."
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
        ]
        read_only_fields = ["organizador"]

# Valida el sector y la cantidad solicitada.
# El carro se asigna desde el usuario autenticado.
class ItemCarroSerializer(serializers.ModelSerializer):
    sector = serializers.PrimaryKeyRelatedField(
        queryset=Sector.objects.filter(evento__activo=True)
    )
    cantidad = serializers.IntegerField(min_value=1)
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
            "sector_nombre",
            "evento_nombre",
            "cantidad",
            "precio_unitario",
        ]
        read_only_fields = ["id"]