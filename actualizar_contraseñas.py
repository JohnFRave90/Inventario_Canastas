from werkzeug.security import generate_password_hash
import sqlite3

def obtener_conexion():
    return sqlite3.connect('db/inventario.db')

def actualizar_contraseñas():
    conn = obtener_conexion()
    cursor = conn.cursor()

    # Seleccionar todos los usuarios con sus contraseñas en texto plano
    cursor.execute('SELECT id, password FROM usuarios')
    usuarios = cursor.fetchall()

    for usuario in usuarios:
        id_usuario = usuario[0]
        contraseña_plana = usuario[1]
        
        # Hashear la contraseña con bcrypt
        hashed_password = generate_password_hash(contraseña_plana)
        
        # Actualizar la contraseña hasheada en la base de datos
        print(f"Depuración: Actualizando usuario {id_usuario} con contraseña hasheada: {hashed_password}")

        cursor.execute('UPDATE usuarios SET password = ? WHERE id = ?', (hashed_password, id_usuario))
    
    conn.commit()
    conn.close()
    print("Depuración: Contraseñas actualizadas correctamente con bcrypt.")

# Ejecutar la función para actualizar las contraseñas
if __name__ == "__main__":
    actualizar_contraseñas()
    print("Contraseñas actualizadas con éxito")
