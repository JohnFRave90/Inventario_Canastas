from werkzeug.security import generate_password_hash, check_password_hash

# Cuando guardes las contraseñas en la base de datos, usa bcrypt
def generar_hash_contraseña(password):
    return generate_password_hash(password)

# Ejemplo de cómo almacenar contraseñas al registrarse
hashed_password = generar_hash_contraseña("despachos2025")

# Ahora, para verificar la contraseña ingresada
def verificar_contraseña(hash_guardado, password_ingresada):
    return check_password_hash(hash_guardado, password_ingresada)
