from werkzeug.security import generate_password_hash
import sqlite3

def obtener_conexion():
    return sqlite3.connect('db/inventario.db')

def actualizar_contraseñas():
    conn = obtener_conexion()
    cursor = conn.cursor()

    # Seleccionar todos los usuarios y sus contraseñas actuales
    cursor.execute('SELECT id, password FROM usuarios')
    usuarios = cursor.fetchall()

    for usuario in usuarios:
        id_usuario = usuario[0]
        contraseña_plana = usuario[1]
        
        print(f"Depuración: Usuario ID {id_usuario}, Contraseña (texto plano): {contraseña_plana}")  # Mostrar contraseña en texto plano

        # Hashear la contraseña
        hashed_password = generate_password_hash(contraseña_plana)
        
        # Actualizar la contraseña hasheada en la base de datos
        print(f"Depuración: Contraseña hasheada: {hashed_password}")  # Verificar el hash generado

        cursor.execute('UPDATE usuarios SET password = ? WHERE id = ?', (hashed_password, id_usuario))
    
    conn.commit()
    conn.close()
    print("Depuración: Contraseñas actualizadas correctamente")

# Ejecutar la función para actualizar las contraseñas
if __name__ == "__main__":
    actualizar_contraseñas()
    print("Contraseñas actualizadas con éxito")
