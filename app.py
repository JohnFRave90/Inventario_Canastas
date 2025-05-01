from flask import Flask, render_template, request, redirect, url_for, flash, session
import pandas as pd
from flask import send_file, Response
import csv
import io
import sqlite3
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
import os
import base64
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = 'secret_key'  # Para manejar las alertas (flashes)

# Obtener la ruta de la base de datos desde una variable de entorno
#db_path = os.getenv("DATABASE_URL", "'/home/JohnRave/Inventario_Canastas/db/Inventario.db'")
db_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'db', 'inventario.db')

# Función para obtener la conexión con la base de datos
def obtener_conexion():
    conn = sqlite3.connect(db_path)
    return conn

# Decorador para restringir acceso a administradores
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session['role'] != 'admin':
            flash('No tienes permisos para acceder a esta página')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Función para obtener los datos del resumen de canastas y el gráfico de vendedores
@app.route('/')
def index():
    # Verificar si el usuario está autenticado
    if 'user_id' not in session:
        flash('Por favor, inicia sesión para acceder a la página principal.')
        return redirect(url_for('login'))  # Redirige al login si no está autenticado
    
    try:
        # Conexión a la base de datos
        conn = obtener_conexion()
        cursor = conn.cursor()

        # Total de canastas
        cursor.execute('SELECT COUNT(*) FROM canastas')
        total_canastas = cursor.fetchone()[0]

        # Total de canastas disponibles
        cursor.execute('SELECT COUNT(*) FROM canastas WHERE actualidad = "Disponible"')
        disponibles = cursor.fetchone()[0]

        # Total de canastas prestadas
        cursor.execute('SELECT COUNT(*) FROM canastas WHERE actualidad = "Prestada"')
        prestadas = cursor.fetchone()[0]

        # Canastas perdidas (prestadas más de una semana)
        fecha_limite = (datetime.now() - timedelta(weeks=1)).strftime('%Y-%m-%d')
        cursor.execute(''' 
            SELECT COUNT(*) FROM movimientos m
            JOIN canastas c ON m.codigo_barras = c.codigo_barras
            WHERE m.tipo = 'Sale' AND m.fecha < ? AND c.actualidad = 'Prestada'
            AND m.codigo_barras NOT IN (
                SELECT codigo_barras FROM movimientos WHERE tipo = 'Entra' AND codigo_barras = m.codigo_barras
            )
        ''', (fecha_limite,))
        canastas_perdidas = cursor.fetchone()[0]

        # Consultar cuántas canastas tiene actualmente prestadas cada vendedor
        cursor.execute(''' 
            SELECT v.nombre, 
                   SUM(CASE WHEN m.tipo = 'Sale' THEN 1 ELSE 0 END) - 
                   SUM(CASE WHEN m.tipo = 'Entra' THEN 1 ELSE 0 END) AS canastas_prestadas_activas
            FROM movimientos m
            JOIN vendedores v ON m.vendedor_codigo = v.codigo
            GROUP BY v.nombre
        ''')
        vendedores = cursor.fetchall()

        # Cerrar la conexión
        conn.close()

        # Crear gráfico de barras para las canastas prestadas activas por vendedor
        vendedores_nombres = [v[0] for v in vendedores]
        canastas_prestadas_activas = [v[1] for v in vendedores]

        fig, ax = plt.subplots(figsize=(8, 6))
        ax.bar(vendedores_nombres, canastas_prestadas_activas, color='#e84a1d')
        ax.set_xlabel('Vendedores')
        ax.set_ylabel('Canastas Prestadas')
        ax.set_title('Canastas Prestadas por Vendedor')

        # Incluir la inclinación de 10 grados para los nombres de los vendedores
        ax.set_xticklabels(vendedores_nombres, rotation=10)  # Esta línea aplica la inclinación

        # Convertir el gráfico a imagen base64 para incrustarlo en el HTML
        img = io.BytesIO()
        FigureCanvas(fig).print_png(img)
        img.seek(0)
        plot_url = base64.b64encode(img.getvalue()).decode('utf8')

        # Pasar los datos a la plantilla HTML
        return render_template('index.html', 
                               total_canastas=total_canastas, 
                               disponibles=disponibles, 
                               prestadas=prestadas, 
                               canastas_perdidas=canastas_perdidas, 
                               plot_url=plot_url)

    except sqlite3.Error as e:
        flash(f'Error al obtener los datos: {e}')
        return redirect(url_for('index'))


# ===================== Vendedores =====================

# Ruta para agregar un vendedor
@app.route('/vendedores', methods=['GET', 'POST'])
def vendedores():
    if request.method == 'POST':
        codigo = request.form['codigo']
        nombre = request.form['nombre']
        
        # Validar que los campos no estén vacíos
        if not (codigo and nombre):
            flash('Todos los campos son obligatorios')
            return redirect(url_for('vendedores'))
        
        # Insertar en la base de datos
        try:
            conn = obtener_conexion()
            cursor = conn.cursor()
            cursor.execute(''' 
                INSERT INTO vendedores (codigo, nombre)
                VALUES (?, ?)
            ''', (codigo, nombre))
            conn.commit()
            conn.close()
            flash('Vendedor registrado con éxito')
        except sqlite3.Error as e:
            flash(f'Error al registrar el vendedor: {e}')
        
        return redirect(url_for('vendedores'))

    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM vendedores')
    vendedores = cursor.fetchall()
    conn.close()
    
    return render_template('vendedores.html', vendedores=vendedores)

# Ruta para eliminar un vendedor (solo administradores)
@app.route('/eliminar_vendedor', methods=['POST'])
@admin_required
def eliminar_vendedor():
    codigo = request.form['codigo']
    
    if not codigo:
        flash('Debe ingresar el código del vendedor')
        return redirect(url_for('vendedores'))

    try:
        conn = obtener_conexion()
        cursor = conn.cursor()
        cursor.execute('''DELETE FROM vendedores WHERE codigo = ?''', (codigo,))
        conn.commit()
        conn.close()

        flash('Vendedor eliminado con éxito')
    except sqlite3.Error as e:
        flash(f'Error al eliminar el vendedor: {e}')

    return redirect(url_for('vendedores'))

# Ruta para modificar un vendedor (solo administradores)
@app.route('/modificar_vendedor', methods=['POST'])
@admin_required
def modificar_vendedor():
    codigo = request.form['codigo']
    nombre = request.form['nombre']
    
    if not (codigo and nombre):
        flash('Todos los campos son obligatorios')
        return redirect(url_for('vendedores'))
    
    try:
        conn = obtener_conexion()
        cursor = conn.cursor()
        cursor.execute('''UPDATE vendedores SET nombre = ? WHERE codigo = ?''', (nombre, codigo))
        conn.commit()
        conn.close()
        
        flash('Vendedor modificado con éxito')
    except sqlite3.Error as e:
        flash(f'Error al modificar el vendedor: {e}')
    
    return redirect(url_for('vendedores'))

@app.route('/exportar_vendedores_csv', methods=['GET'])
def exportar_vendedores_csv():
    try:
        # Conexión a la base de datos
        conn = obtener_conexion()
        cursor = conn.cursor()

        # Obtener todos los vendedores
        cursor.execute('SELECT * FROM vendedores')
        vendedores = cursor.fetchall()

        # Cerrar la conexión
        conn.close()

        # Definir el encabezado de las columnas del CSV
        header = ["Código", "Nombre"]

        # Crear el archivo CSV en memoria y escribir los datos
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(header)
        writer.writerows(vendedores)

        # Mover el cursor al principio del archivo para la descarga
        output.seek(0)

        # Enviar el archivo CSV como una respuesta de descarga
        return Response(output, mimetype='text/csv', headers={
            'Content-Disposition': 'attachment;filename=vendedores.csv'})

    except Exception as e:
        flash(f'Error al exportar los vendedores a CSV: {e}')
        return redirect(url_for('index'))

# ===================== Canastas =====================
# Ruta para registrar canastas
@app.route('/canastas', methods=['GET', 'POST'])
def canastas():
    if request.method == 'POST':
        codigo_barras = request.form['codigo_barras']
        tamano = request.form['tamano']
        color = request.form['color']
        estado = request.form['estado']
        actualidad = request.form['actualidad']
        fecha_registro = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if not (codigo_barras and tamano and color and estado and actualidad):
            flash('Todos los campos son obligatorios')
            return redirect(url_for('canastas'))

        try:
            conn = obtener_conexion()
            cursor = conn.cursor()
            cursor.execute(''' 
                INSERT INTO canastas (codigo_barras, tamano, color, estado, fecha_registro, actualidad)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (codigo_barras, tamano, color, estado, fecha_registro, actualidad))
            conn.commit()
            conn.close()

            flash('Canasta registrada con éxito')
        except sqlite3.Error as e:
            flash(f'Error al registrar la canasta: {e}')
        
        return redirect(url_for('canastas'))

    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM canastas')
    canastas = cursor.fetchall()
    conn.close()
    
    return render_template('canastas.html', canastas=canastas)

#Ruta para exportar a excel las canastas
@app.route('/exportar_canastas', methods=['GET'])
def exportar_canastas():
    try:
        # Conexión a la base de datos
        conn = obtener_conexion()
        cursor = conn.cursor()

        # Obtener todas las canastas
        cursor.execute('SELECT * FROM canastas')
        canastas = cursor.fetchall()

        # Cerrar la conexión
        conn.close()

        # Crear un DataFrame de Pandas con los datos de las canastas
        df = pd.DataFrame(canastas, columns=["Código de Barras", "Tamaño", "Color", "Estado", "Fecha de Registro", "Actualidad"])

        # Crear un archivo Excel en memoria
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Canastas')
            writer.save()

        output.seek(0)

        # Devolver el archivo Excel como una descarga
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name="canastas.xlsx")

    except Exception as e:
        flash(f'Error al exportar las canastas a Excel: {e}')
        return redirect(url_for('index'))

@app.route('/exportar_canastas_csv', methods=['GET'])
def exportar_canastas_csv():
    try:
        # Conexión a la base de datos
        conn = obtener_conexion()
        cursor = conn.cursor()

        # Obtener todas las canastas
        cursor.execute('SELECT * FROM canastas')
        canastas = cursor.fetchall()

        # Cerrar la conexión
        conn.close()

        # Definir el encabezado de las columnas del CSV
        header = ["Código de Barras", "Tamaño", "Color", "Estado", "Fecha de Registro", "Actualidad"]

        # Crear el archivo CSV en memoria y escribir los datos
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(header)
        writer.writerows(canastas)

        # Mover el cursor al principio del archivo para la descarga
        output.seek(0)

        # Enviar el archivo CSV como una respuesta de descarga
        return Response(output, mimetype='text/csv', headers={
            'Content-Disposition': 'attachment;filename=canastas.csv'})

    except Exception as e:
        flash(f'Error al exportar las canastas a CSV: {e}')
        return redirect(url_for('index'))

# ===================== Movimientos =====================

# Ruta para registrar movimientos
@app.route('/movimientos', methods=['GET', 'POST'])
def movimientos():
    # Inicializar contador de registros exitosos si no está en la sesión
    if 'contador_registros' not in session:
        session['contador_registros'] = 0

    if request.method == 'POST':
        vendedor_nombre = request.form['vendedor']  # Nombre del vendedor
        tipo = request.form['tipo']  # Tipo de movimiento (sale o entra)
        codigo_barras = request.form['codigo_barras']
        
        # Validar los campos
        if not (vendedor_nombre and tipo and codigo_barras):
            flash('Todos los campos son obligatorios')
            return redirect(url_for('movimientos'))

        try:
            # Obtener el código del vendedor por su nombre
            conn = obtener_conexion()
            cursor = conn.cursor()
            cursor.execute('SELECT codigo FROM vendedores WHERE nombre = ?', (vendedor_nombre,))
            vendedor = cursor.fetchone()

            if not vendedor:
                flash('Vendedor no encontrado')
                return redirect(url_for('movimientos'))
            
            vendedor_codigo = vendedor[0]  # Extraer el código del vendedor

            # Verificar el estado de la canasta antes de registrar el movimiento
            cursor.execute('SELECT actualidad FROM canastas WHERE codigo_barras = ?', (codigo_barras,))
            canasta = cursor.fetchone()

            if not canasta:
                flash('Canasta no encontrada')
                return redirect(url_for('movimientos'))

            estado_canasta = canasta[0]  # Estado actual de la canasta

            # Consultar la última transacción para la canasta, si existe
            cursor.execute('''
                SELECT vendedor_codigo, tipo FROM movimientos 
                WHERE codigo_barras = ? 
                ORDER BY fecha DESC LIMIT 1
            ''', (codigo_barras,))
            ultima_transaccion = cursor.fetchone()

            if tipo == 'Entra' and not ultima_transaccion:
                flash('No se ha registrado ningún movimiento para esta canasta, no se puede devolver.')
                return redirect(url_for('movimientos'))

            if ultima_transaccion:
                vendedor_ultimo, tipo_ultimo = ultima_transaccion

                # Verificar si el vendedor que intenta devolver la canasta es el que la prestó
                if tipo == 'Entra' and vendedor_ultimo != vendedor_codigo:
                    flash('¡Esta canasta ha sido prestada a otro vendedor! No puedes devolverla.')
                    return redirect(url_for('movimientos'))

            # Validar si el movimiento es válido
            if tipo == 'Sale' and estado_canasta == 'Prestada':
                flash('¡Esta canasta ya ha sido prestada anteriormente!')
                return redirect(url_for('movimientos'))

            if tipo == 'Entra' and estado_canasta == 'Disponible':
                flash('¡Esta canasta no ha sido prestada!')
                return redirect(url_for('movimientos'))

            # Registrar el movimiento en la tabla movimientos
            cursor.execute(''' 
                INSERT INTO movimientos (vendedor_codigo, tipo, codigo_barras, fecha)
                VALUES (?, ?, ?, ?)
            ''', (vendedor_codigo, tipo, codigo_barras, datetime.now()))

            # Actualizar el estado de la canasta según el tipo de movimiento
            if tipo == 'Sale' and estado_canasta == 'Disponible':
                cursor.execute('UPDATE canastas SET actualidad = ? WHERE codigo_barras = ?', ('Prestada', codigo_barras))
            elif tipo == 'Entra' and estado_canasta == 'Prestada':
                cursor.execute('UPDATE canastas SET actualidad = ? WHERE codigo_barras = ?', ('Disponible', codigo_barras))

            conn.commit()
            conn.close()

            flash('Movimiento registrado con éxito')

            # Verificar si el vendedor o el tipo de movimiento han cambiado
            if vendedor_nombre != session.get('vendedor_seleccionado') or tipo != session.get('tipo_seleccionado'):
                session['contador_registros'] = 0  # Reiniciar el contador de registros

            # Actualizar la sesión con los nuevos valores seleccionados
            session['vendedor_seleccionado'] = vendedor_nombre
            session['tipo_seleccionado'] = tipo
            session['codigo_barras'] = ''  # Vaciar el campo de código de barras

            # Incrementar el contador de registros exitosos
            session['contador_registros'] += 1

        except sqlite3.Error as e:
            flash(f'Error al registrar el movimiento: {e}')

        return redirect(url_for('movimientos'))  # Redirigir a la misma página para mostrar el resultado

    # Obtener la lista de vendedores ordenada alfabéticamente por su nombre
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('SELECT nombre FROM vendedores ORDER BY nombre ASC')
    vendedores = cursor.fetchall()

    # Obtener los 100 movimientos más recientes, ordenados de más reciente a más antiguo
    cursor.execute(''' 
        SELECT m.fecha, v.nombre, m.tipo, m.codigo_barras 
        FROM movimientos m 
        JOIN vendedores v ON m.vendedor_codigo = v.codigo 
        ORDER BY m.fecha DESC 
        LIMIT 100
    ''')
    movimientos = cursor.fetchall()

    conn.close()

    # Obtener los valores previamente seleccionados para mostrar en el formulario
    vendedor_seleccionado = session.get('vendedor_seleccionado', '')
    tipo_seleccionado = session.get('tipo_seleccionado', '')
    codigo_barras = session.get('codigo_barras', '')  # El campo se vacía en la sesión

    return render_template('movimientos.html', 
                           vendedores=vendedores, 
                           vendedor_seleccionado=vendedor_seleccionado, 
                           tipo_seleccionado=tipo_seleccionado, 
                           codigo_barras=codigo_barras,
                           contador_registros=session['contador_registros'],
                           movimientos=movimientos)


# Ruta para ver los movimientos registrados
@app.route('/ver_movimientos')
def ver_movimientos():
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.id, v.nombre, m.tipo, m.codigo_barras, m.fecha
        FROM movimientos m
        JOIN vendedores v ON m.vendedor_codigo = v.codigo
    ''')
    movimientos = cursor.fetchall()
    conn.close()
    
    return render_template('movimientos.html', movimientos=movimientos)

# ===================== Reportes =====================

# Función para generar el informe de canastas
@app.route('/generar_informe_canastas')
def generar_informe_canastas():
    conn = obtener_conexion()
    cursor = conn.cursor()
    
    # Obtener el número de canastas disponibles y prestadas
    cursor.execute('''
        SELECT COUNT(*) FROM canastas WHERE actualidad = "Disponible"
    ''')
    disponibles = cursor.fetchone()[0]

    cursor.execute('''
        SELECT COUNT(*) FROM canastas WHERE actualidad = "Prestada"
    ''')
    prestadas = cursor.fetchone()[0]

    cursor.execute('''
        SELECT COUNT(*) FROM canastas
    ''')
    total_canastas = cursor.fetchone()[0]
    
    conn.close()

    # Renderizar el informe en la plantilla
    return render_template('informe_canastas.html', disponibles=disponibles, prestadas=prestadas, total_canastas=total_canastas)

# Función para generar el informe de movimientos
@app.route('/generar_informe_movimientos')
def generar_informe_movimientos():
    conn = obtener_conexion()
    cursor = conn.cursor()
    
    # Obtener movimientos
    cursor.execute('''
        SELECT v.nombre, m.tipo, m.codigo_barras, m.fecha
        FROM movimientos m
        JOIN vendedores v ON m.vendedor_codigo = v.codigo
    ''')
    movimientos = cursor.fetchall()
    conn.close()

    # Renderizar el informe en la plantilla
    return render_template('informe_movimientos.html', movimientos=movimientos)


# Ruta para generar el informe de canastas
@app.route('/informe_canastas', methods=['GET'])
def informe_canastas():
    try:
        # Conexión a la base de datos
        conn = obtener_conexion()
        cursor = conn.cursor()

        # Consulta para obtener el tamaño, color y disponibilidad de las canastas
        cursor.execute('''
            SELECT tamano, color,
                SUM(CASE WHEN actualidad = 'Disponible' THEN 1 ELSE 0 END) AS disponibles,
                SUM(CASE WHEN actualidad = 'Prestada' THEN 1 ELSE 0 END) AS prestadas,
                COUNT(*) AS total
            FROM canastas
            GROUP BY tamano, color
        ''')

        canastas = cursor.fetchall()

        # Verificar si no se obtuvieron datos
        if not canastas:
            flash('No se encontraron canastas en el informe')
            return render_template('informe_canastas.html', canastas=canastas)

        # Almacenar los datos de las canastas en la sesión
        session['canastas'] = canastas
    
        conn.close()

        # Si se hace una solicitud para exportar el informe a CSV
        if 'export' in request.args:
            flash("Exportación a CSV activada")
            return exportar_a_csv_canastas()

        # Mostrar el informe en una página HTML
        return render_template('informe_canastas.html', canastas=canastas)

    except Exception as e:
        flash(f'Ocurrió un error al generar el informe: {e}')
        return render_template('informe_canastas.html', canastas=[])

def exportar_a_csv_canastas():
    # Recuperar los datos de las canastas desde la sesión
    canastas = session.get('canastas', [])

    # Verificar si se recuperaron datos de la sesión
    if not canastas:
        flash('No se encontraron datos para exportar')
        return redirect(url_for('informe_canastas'))

    flash(f"Datos que se exportarán a CSV: {canastas}")

    import csv
    import io

    # Crear un archivo CSV en memoria
    output = io.StringIO()
    writer = csv.writer(output)

    # Escribir el encabezado en el archivo CSV
    writer.writerow(['Tamaño', 'Color', 'Canastas Disponibles', 'Canastas Prestadas', 'Total Canastas'])

    # Escribir los datos de las canastas
    for canasta in canastas:
        writer.writerow(canasta)

    # Mover el cursor al inicio del archivo para la descarga
    output.seek(0)

    # Enviar el archivo CSV como respuesta de descarga
    return Response(output, mimetype='text/csv', headers={
        'Content-Disposition': 'attachment; filename=informe_canastas.csv'
    })


# Ruta para generar el informe de movimientos
@app.route('/informe_movimientos', methods=['GET'])
def informe_movimientos():
    try:
        # Obtener las fechas de inicio y fin del rango desde la URL
        fecha_inicio = request.args.get('fecha_inicio')
        fecha_fin = request.args.get('fecha_fin')

        # Verificar si las fechas están presentes en la URL, si no las tomamos de la sesión
        if not fecha_inicio or not fecha_fin:
            fecha_inicio = session.get('fecha_inicio')
            fecha_fin = session.get('fecha_fin')

            if not fecha_inicio or not fecha_fin:
                flash('Por favor, selecciona un rango de fechas')
                return render_template('informe_movimientos.html', movimientos=[])

        # Almacenar las fechas en la sesión para su uso en la exportación
        session['fecha_inicio'] = fecha_inicio
        session['fecha_fin'] = fecha_fin

        # Ajustar la hora para fecha_inicio a las 12:00 AM y fecha_fin a las 11:59 PM
        fecha_inicio = f"{fecha_inicio} 00:00:00"
        fecha_fin = f"{fecha_fin} 23:59:59"

        # Conectar a la base de datos y realizar la consulta
        conn = obtener_conexion()
        cursor = conn.cursor()

        cursor.execute(''' 
            SELECT m.fecha, v.nombre, m.tipo, m.codigo_barras 
            FROM movimientos m 
            JOIN vendedores v ON m.vendedor_codigo = v.codigo
            WHERE m.fecha BETWEEN ? AND ?
            ORDER BY m.fecha DESC
        ''', (fecha_inicio, fecha_fin))

        movimientos = cursor.fetchall()
        conn.close()

        # Si se hace una solicitud para exportar, generamos el archivo CSV
        if 'export' in request.args:
            return exportar_a_csv_movimientos(movimientos, fecha_inicio, fecha_fin)

        # Renderizar la plantilla HTML con los movimientos filtrados
        return render_template('informe_movimientos.html', movimientos=movimientos)

    except Exception as e:
        flash(f'Ocurrió un error al generar el informe: {e}')
        return render_template('informe_movimientos.html', movimientos=[])

def exportar_a_csv_movimientos(movimientos, fecha_inicio, fecha_fin):
    import csv
    import io

    # Crear un archivo CSV en memoria
    output = io.StringIO()
    writer = csv.writer(output)

    # Escribir el encabezado en el archivo CSV
    writer.writerow(['Fecha', 'Vendedor', 'Tipo', 'Código de Barras'])

    # Escribir los datos de los movimientos
    for movimiento in movimientos:
        writer.writerow(movimiento)

    # Mover el cursor al inicio del archivo para la descarga
    output.seek(0)

    # Enviar el archivo CSV como respuesta de descarga
    return Response(output, mimetype='text/csv', headers={
        'Content-Disposition': f'attachment; filename=informe_movimientos_{fecha_inicio}_{fecha_fin}.csv'
    })


# Ruta para generar el informe de movimientos
@app.route('/informe_vendedores', methods=['GET'])
def informe_vendedores():
    try:
        # Obtener la fecha de la solicitud
        fecha = request.args.get('fecha')

        # Verificar si la fecha está presente
        if not fecha:
            flash('Por favor, selecciona una fecha')
            return render_template('informe_vendedores.html', vendedores=[])

        # Ajustar la hora para la fecha seleccionada a las 12:00 AM
        fecha_inicio = f"{fecha} 00:00:00"
        fecha_fin = f"{fecha} 23:59:59"

        # Conectar a la base de datos
        conn = obtener_conexion()
        cursor = conn.cursor()

        # Consulta para obtener el número de canastas prestadas y devueltas por vendedor en esa fecha
        cursor.execute('''
            SELECT v.nombre, 
                   SUM(CASE WHEN m.tipo = 'Sale' THEN 1 ELSE 0 END) AS canastas_prestadas,
                   SUM(CASE WHEN m.tipo = 'Entra' THEN 1 ELSE 0 END) AS canastas_devueltas
            FROM movimientos m
            JOIN vendedores v ON m.vendedor_codigo = v.codigo
            WHERE m.fecha BETWEEN ? AND ?
            GROUP BY v.nombre
        ''', (fecha_inicio, fecha_fin))

        vendedores = cursor.fetchall()
        conn.close()

        # Si no hay vendedores, devolver un mensaje de error
        if not vendedores:
            flash('No se encontraron movimientos para esta fecha')
            return render_template('informe_vendedores.html', vendedores=[])

        # Si se hace una solicitud para exportar el informe a CSV
        if 'export' in request.args:
            return exportar_a_csv(vendedores, fecha)

        return render_template('informe_vendedores.html', vendedores=vendedores)

    except Exception as e:
        flash(f'Ocurrió un error al generar el informe: {e}')
        return render_template('informe_vendedores.html', vendedores=[])

def exportar_a_csv(vendedores, fecha):
    # Crear un archivo CSV en memoria
    output = io.StringIO()
    writer = csv.writer(output)

    # Escribir el encabezado en el archivo CSV
    writer.writerow(['Vendedor', 'Canastas Prestadas', 'Canastas Devueltas'])

    # Escribir los datos de los vendedores
    for vendedor in vendedores:
        writer.writerow(vendedor)

    # Mover el cursor al inicio del archivo para la descarga
    output.seek(0)

    # Enviar el archivo CSV como respuesta de descarga
    return Response(output, mimetype='text/csv', headers={
        'Content-Disposition': f'attachment; filename=informe_vendedores_{fecha}.csv'
    })
   
   
# Ruta para generar el informe de busqueda de canasta
@app.route('/informe_buscar_canasta', methods=['GET', 'POST'])
def informe_buscar_canasta():
    if request.method == 'POST':
        # Obtener el código de barras de la canasta ingresado por el usuario
        codigo_barras = request.form['codigo_barras']

        # Validar que el código de barras no esté vacío
        if not codigo_barras:
            flash('Por favor ingrese un código de barras')
            return render_template('informe_buscar_canasta.html', canasta=None, movimientos=[])

        # Conectar a la base de datos
        conn = obtener_conexion()
        cursor = conn.cursor()

        # Consultar detalles de la canasta (tamaño y color)
        cursor.execute('''
            SELECT tamano, color
            FROM canastas
            WHERE codigo_barras = ?
        ''', (codigo_barras,))

        canasta = cursor.fetchone()

        if not canasta:
            flash('Canasta no encontrada')
            return render_template('informe_buscar_canasta.html', canasta=None, movimientos=[])

        # Consultar los últimos 30 movimientos de la canasta
        cursor.execute('''
            SELECT m.fecha, v.nombre, m.tipo
            FROM movimientos m
            JOIN vendedores v ON m.vendedor_codigo = v.codigo
            WHERE m.codigo_barras = ?
            ORDER BY m.fecha DESC
            LIMIT 30
        ''', (codigo_barras,))

        movimientos = cursor.fetchall()
        conn.close()

        # Devolver los resultados de la búsqueda
        return render_template('informe_buscar_canasta.html', canasta=canasta, movimientos=movimientos)

    return render_template('informe_buscar_canasta.html', canasta=None, movimientos=[])

@app.route('/exportar_csv_canasta', methods=['GET'])
def exportar_csv_canasta():
    # Recuperar el código de barras de la URL
    codigo_barras = request.args.get('codigo_barras')

    # Conectar a la base de datos
    conn = obtener_conexion()
    cursor = conn.cursor()

    # Consultar detalles de la canasta (tamaño y color)
    cursor.execute('''
        SELECT tamano, color
        FROM canastas
        WHERE codigo_barras = ?
    ''', (codigo_barras,))

    canasta = cursor.fetchone()

    if not canasta:
        flash('Canasta no encontrada')
        return redirect(url_for('informe_buscar_canasta'))

    # Consultar los últimos 30 movimientos de la canasta
    cursor.execute('''
        SELECT m.fecha, v.nombre, m.tipo
        FROM movimientos m
        JOIN vendedores v ON m.vendedor_codigo = v.codigo
        WHERE m.codigo_barras = ?
        ORDER BY m.fecha DESC
        LIMIT 30
    ''', (codigo_barras,))

    movimientos = cursor.fetchall()
    conn.close()

    # Generar el archivo CSV
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    # Escribir el encabezado en el archivo CSV
    writer.writerow(['Fecha y Hora', 'Vendedor', 'Tipo de Movimiento'])

    # Escribir los datos de los movimientos
    for movimiento in movimientos:
        writer.writerow(movimiento)

    # Mover el cursor al inicio del archivo para la descarga
    output.seek(0)

    # Enviar el archivo CSV como respuesta de descarga
    return Response(output, mimetype='text/csv', headers={
        'Content-Disposition': f'attachment; filename=movimientos_canasta_{codigo_barras}.csv'
    })


# Ruta para generar el informe de cuantas y cuales canastas tiene prestadas un vendedor
@app.route('/informe_canastas_por_vendedor', methods=['GET', 'POST'])
def informe_canastas_por_vendedor():
    # Obtener la lista de vendedores para mostrarla en el formulario
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('SELECT nombre FROM vendedores ORDER BY nombre')
    vendedores = cursor.fetchall()

    # Si el formulario se envía
    if request.method == 'POST':
        # Obtener el vendedor seleccionado
        vendedor_nombre = request.form['vendedor']

        # Consultar el código del vendedor
        cursor.execute('SELECT codigo FROM vendedores WHERE nombre = ?', (vendedor_nombre,))
        vendedor = cursor.fetchone()

        if not vendedor:
            flash('Vendedor no encontrado')
            return render_template('informe_canastas_por_vendedor.html', vendedores=vendedores, canastas=[], resumen={})

        vendedor_codigo = vendedor[0]

        # Obtener las canastas prestadas activas (no devueltas)
        cursor.execute('''
            SELECT c.tamano, c.color, COUNT(*) 
            FROM canastas c
            JOIN movimientos m ON c.codigo_barras = m.codigo_barras
            WHERE m.vendedor_codigo = ? AND m.tipo = 'Sale' AND c.actualidad = 'Prestada'
            AND NOT EXISTS (
                SELECT 1 FROM movimientos m2
                WHERE m2.codigo_barras = m.codigo_barras AND m2.tipo = 'Entra'
            )
            GROUP BY c.tamano, c.color
        ''', (vendedor_codigo,))

        resumen = cursor.fetchall()

        # Obtener los detalles de las canastas prestadas y no devueltas
        cursor.execute('''
            SELECT c.codigo_barras, c.tamano, c.color, m.fecha 
            FROM canastas c
            JOIN movimientos m ON c.codigo_barras = m.codigo_barras
            WHERE m.vendedor_codigo = ? AND m.tipo = 'Sale' AND c.actualidad = 'Prestada'
            AND NOT EXISTS (
                SELECT 1 FROM movimientos m2
                WHERE m2.codigo_barras = m.codigo_barras AND m2.tipo = 'Entra'
            )
            ORDER BY m.fecha DESC
        ''', (vendedor_codigo,))

        canastas = cursor.fetchall()
        conn.close()

        # Devolver los resultados del informe
        return render_template('informe_canastas_por_vendedor.html', vendedores=vendedores, canastas=canastas, resumen=resumen)

    conn.close()

    # Si el formulario no se envía, mostrar la lista de vendedores
    return render_template('informe_canastas_por_vendedor.html', vendedores=vendedores, canastas=[], resumen={})


# Ruta para generar el informe de cuantas canastas tiene prestadas por vendedor
@app.route('/informe_canastas_prestadas_por_vendedor', methods=['GET'])
def informe_canastas_prestadas_por_vendedor():
    try:
        # Conexión a la base de datos
        conn = obtener_conexion()
        cursor = conn.cursor()

        # Consulta para contar cuántas canastas tiene prestadas cada vendedor
        cursor.execute('''
            SELECT v.nombre, 
                   SUM(CASE WHEN m.tipo = 'Sale' THEN 1 ELSE 0 END) - 
                   SUM(CASE WHEN m.tipo = 'Entra' THEN 1 ELSE 0 END) AS canastas_prestadas_activas
            FROM movimientos m
            JOIN vendedores v ON m.vendedor_codigo = v.codigo
            GROUP BY v.nombre
            ORDER BY canastas_prestadas_activas DESC
        ''')

        # Recuperar los resultados
        canastas_prestadas = cursor.fetchall()
        conn.close()

        # Si se hace una solicitud para exportar el informe a CSV
        if 'export' in request.args:
            return exportar_a_csv_canastas_prestadas(canastas_prestadas)

        # Renderizar el informe en una página HTML
        return render_template('informe_canastas_prestadas_por_vendedor.html', canastas_prestadas=canastas_prestadas)

    except Exception as e:
        flash(f'Ocurrió un error al generar el informe: {e}')
        return render_template('informe_canastas_prestadas_por_vendedor.html', canastas_prestadas=[])


# Función para exportar el informe de canastas prestadas a CSV
@app.route('/exportar_csv_canastas_prestadas', methods=['GET'])
def exportar_a_csv_canastas_prestadas(canastas_prestadas):
    import csv
    import io

    # Crear un archivo CSV en memoria
    output = io.StringIO()
    writer = csv.writer(output)

    # Escribir el encabezado en el archivo CSV
    writer.writerow(['Vendedor', 'Canastas Prestadas'])

    # Escribir los datos de las canastas prestadas
    for canasta in canastas_prestadas:
        writer.writerow(canasta)

    # Mover el cursor al inicio del archivo para la descarga
    output.seek(0)

    # Enviar el archivo CSV como respuesta de descarga
    return Response(output, mimetype='text/csv', headers={
        'Content-Disposition': 'attachment; filename=canastas_prestadas_por_vendedor.csv'
    })


# Función borrar todos los movimientos y actualizar canastas a disponibles
@app.route('/borrar_movimientos', methods=['POST'])
@admin_required
def borrar_movimientos():
    try:
        # Conexión a la base de datos
        conn = obtener_conexion()
        cursor = conn.cursor()

        # Borrar todos los movimientos
        cursor.execute('DELETE FROM movimientos')
        
        # Actualizar la actualidad de todas las canastas a 'Disponible'
        cursor.execute('UPDATE canastas SET actualidad = "Disponible"')
        
        conn.commit()
        conn.close()

        flash('Todos los movimientos han sido borrados y las canastas han sido actualizadas a "Disponible"')
    except Exception as e:
        flash(f'Ocurrió un error al borrar los movimientos: {e}')
    return redirect(url_for('index'))


# Función borrar todas las canastas
@app.route('/borrar_canastas', methods=['POST'])
@admin_required
def borrar_canastas():
    try:
        # Conexión a la base de datos
        conn = obtener_conexion()
        cursor = conn.cursor()

        # Borrar todas las canastas
        cursor.execute('DELETE FROM canastas')
        
        conn.commit()
        conn.close()

        flash('Todas las canastas han sido borradas')
    except Exception as e:
        flash(f'Ocurrió un error al borrar las canastas: {e}')
    return redirect(url_for('index'))

# ===================== Usuarios =====================

# Ruta para registrar usuarios (solo administradores)
from werkzeug.security import generate_password_hash, check_password_hash

@app.route('/registrar_usuario', methods=['GET', 'POST'])
@admin_required
def registrar_usuario():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        
        if not username or not password:
            flash('Todos los campos son obligatorios')
            return redirect(url_for('registrar_usuario'))

        try:
            conn = obtener_conexion()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM usuarios WHERE username = ?', (username,))
            if cursor.fetchone():
                flash('El nombre de usuario ya existe')
                return redirect(url_for('registrar_usuario'))

            # Hashear la contraseña antes de guardarla
            hashed_password = generate_password_hash(password)

            cursor.execute('''
                INSERT INTO usuarios (username, password, role)
                VALUES (?, ?, ?)
            ''', (username, hashed_password, role))
            conn.commit()
            conn.close()
            flash('Usuario registrado con éxito')
        except sqlite3.Error as e:
            flash(f'Error al registrar el usuario: {e}')
        
        return redirect(url_for('index'))
    
    return render_template('registrar_usuario.html')

# Ruta para iniciar sesión
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if not username or not password:
            flash('Por favor ingrese un nombre de usuario y una contraseña')
            return redirect(url_for('login'))

        try:
            conn = obtener_conexion()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM usuarios WHERE username = ?', (username,))
            user = cursor.fetchone()

            if user:
                # Verificar si la contraseña proporcionada coincide con el hash almacenado
                if check_password_hash(user[2], password):  # user[2] contiene el hash de la contraseña
                    session['user_id'] = user[0]
                    session['role'] = user[3]
                    flash('Login exitoso')
                    return redirect(url_for('index'))  # Redirigir a la página de inicio
                else:
                    flash('Contraseña incorrecta')
            else:
                flash('Usuario no encontrado')

        except sqlite3.Error as e:
            flash(f'Error al intentar iniciar sesión: {e}')
    
    return render_template('login.html')

# Ruta para cerrar sesión
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('role', None)
    flash('Has cerrado sesión exitosamente')
    return redirect(url_for('login'))  # Redirige al login después de cerrar sesión

# Obtener las contraseñas antiguas y actualizarlas como hashes
def actualizar_contraseñas():
    conn = obtener_conexion()
    cursor = conn.cursor()

    # Seleccionar todos los usuarios sin contraseña hasheada
    cursor.execute('SELECT id, password FROM usuarios')
    usuarios = cursor.fetchall()

    for usuario in usuarios:
        id_usuario = usuario[0]
        contraseña_plana = usuario[1]
        
        # Hashear la contraseña
        hashed_password = generate_password_hash(contraseña_plana)
        
        # Actualizar la contraseña hasheada en la base de datos
        cursor.execute('UPDATE usuarios SET password = ? WHERE id = ?', (hashed_password, id_usuario))
    
    conn.commit()
    conn.close()

@app.route('/actualizar_contraseñas')
def actualizar_contraseñas_route():
    try:
        actualizar_contraseñas()
        flash('Las contraseñas se han actualizado correctamente.')
    except Exception as e:
        flash(f'Error al actualizar las contraseñas: {e}')
    
    return redirect(url_for('index'))


# ===================== Iniciar la aplicación =====================

# Función para ejecutar la aplicación
if __name__ == '__main__':
    app.run(debug=True)