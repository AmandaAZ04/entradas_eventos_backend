from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializer import LoginSerializer


# Permite iniciar sesión sin tener un token previo.
# SimpleJWT verifica el usuario y la contraseña.
class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]