from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


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