"""Reglas compartidas por registro y administración de contraseñas."""

import re
import unicodedata

from django.core.exceptions import ValidationError


def validar_nombre(value):
    value = " ".join(unicodedata.normalize("NFC", value).split())
    if (
        not value
        or not value[0].isalpha()
        or len(value) > 150
        or not all(c.isalpha() or c in " -'’" for c in value)
    ):
        raise ValidationError("Ingresa un nombre válido, sin números ni símbolos.")
    if not any(c.isalpha() for c in value):
        raise ValidationError("El nombre debe contener letras.")
    return value


def normalizar_rut(value):
    value = value.strip().replace(".", "").replace("-", "").upper()
    if not re.fullmatch(r"[1-9][0-9]{0,7}[0-9K]", value):
        raise ValidationError("Ingresa un RUT válido, con su dígito verificador.")
    numero, digito = value[:-1], value[-1]
    suma = sum(int(n) * (2 + i % 6) for i, n in enumerate(reversed(numero)))
    resultado = 11 - suma % 11
    esperado = "0" if resultado == 11 else "K" if resultado == 10 else str(resultado)
    if digito != esperado:
        raise ValidationError("El dígito verificador del RUT es incorrecto.")
    return f"{numero}-{digito}"


class PasswordRegistroValidator:
    def validate(self, password, user=None):
        errores = []
        if not 8 <= len(password) <= 16:
            errores.append("La contraseña debe tener entre 8 y 16 caracteres.")
        if any(c.isspace() for c in password):
            errores.append("La contraseña no puede contener espacios en blanco.")
        if not any(c.isupper() for c in password) or not any(
            c.islower() for c in password
        ):
            errores.append("Incluye al menos una mayúscula y una minúscula.")
        if not any(c in "@$#*" for c in password):
            errores.append("Incluye al menos un carácter especial: @ $ # *.")
        if not any(c in "0123456789" for c in password):
            errores.append("Incluye al menos un número.")
        if errores:
            raise ValidationError(errores)

    def get_help_text(self):
        return "Entre 8 y 16 caracteres, sin espacios, con mayúscula, minúscula, número y @ $ # *."
