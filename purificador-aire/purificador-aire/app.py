# -*- coding: utf-8 -*-
"""
Sistema de purificación de aire - servidor simple.

Usa SOLO la librería estándar de Python (http.server + sqlite3).
No hay que instalar nada.

Ejecutar:   python app.py
Abrir:      http://localhost:8000
"""
import csv
import io
import json
import math
import os
import random
import re
import sqlite3
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

AQUI = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(AQUI, "aire.db")
PUERTO = 8000

CONT = ["pm25", "pm10", "co2", "co"]
NOMBRES = {"pm25": "PM2.5", "pm10": "PM10", "co2": "CO2", "co": "CO"}
NIVELES = ["Bajo", "Moderado", "Alto", "Crítico"]

# Límite superior de cada nivel (Bajo, Moderado, Alto). Por encima = Crítico.
LIMITES = {
    "pm25": (12, 35, 55),       # µg/m³
    "pm10": (54, 154, 254),     # µg/m³
    "co2": (800, 1000, 2000),   # ppm
    "co": (4, 9, 35),           # ppm
}
MAXIMOS = {"pm25": 1000, "pm10": 2000, "co2": 10000, "co": 1000}

# Eficiencia máxima simulada de cada filtro por contaminante (0 a 1).
# HEPA retiene partículas; el carbón activado adsorbe algunos gases;
# el catalizador/absorbente (sistema completo) ataca CO y CO2.
EFICIENCIA = {
    "HEPA": {"pm25": 0.97, "pm10": 0.98, "co2": 0.00, "co": 0.00},
    "Carbón activado": {"pm25": 0.25, "pm10": 0.30, "co2": 0.10, "co": 0.15},
    "HEPA + Carbón activado": {"pm25": 0.98, "pm10": 0.99, "co2": 0.10, "co": 0.15},
    "Sistema completo": {"pm25": 0.98, "pm10": 0.99, "co2": 0.45, "co": 0.80},
}


# ---------------------------------------------------------------- base de datos
def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def iniciar_db():
    conn = db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS procesos(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_ingreso TEXT NOT NULL,
            pm25_in REAL, pm10_in REAL, co2_in REAL, co_in REAL,
            filtro TEXT, minutos INTEGER, fecha_fin TEXT,
            pm25_out REAL, pm10_out REAL, co2_out REAL, co_out REAL
        );
        CREATE TABLE IF NOT EXISTS lecturas(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proceso_id INTEGER NOT NULL,
            minuto INTEGER,
            pm25 REAL, pm10 REAL, co2 REAL, co REAL
        );
        """
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------ cálculos
def nivel_de(cont, valor):
    for i, limite in enumerate(LIMITES[cont]):
        if valor <= limite:
            return i
    return 3


def reduccion(antes, despues):
    if antes <= 0:
        return 0.0
    return max(0.0, round((antes - despues) / antes * 100, 1))


def recomendar(d):
    n = {c: nivel_de(c, d[c + "_in"]) for c in CONT}
    hay_particulas = max(n["pm25"], n["pm10"]) > 0
    hay_gases = max(n["co2"], n["co"]) > 0
    if hay_gases:
        return "Sistema completo"
    if hay_particulas:
        return "HEPA"
    return "HEPA"


def enriquecer(fila):
    d = dict(fila)
    d["niveles_in"] = {c: NIVELES[nivel_de(c, d[c + "_in"])] for c in CONT}
    d["nivel_in"] = NIVELES[max(nivel_de(c, d[c + "_in"]) for c in CONT)]
    d["recomendado"] = recomendar(d)
    if d["pm25_out"] is None:
        d["estado"] = "Pendiente"
        return d
    d["estado"] = "Purificado"
    d["niveles_out"] = {c: NIVELES[nivel_de(c, d[c + "_out"])] for c in CONT}
    d["nivel_out"] = NIVELES[max(nivel_de(c, d[c + "_out"]) for c in CONT)]
    red = {c: reduccion(d[c + "_in"], d[c + "_out"]) for c in CONT}
    d["reduccion"] = red
    # Eficiencia: promedio de reducción de los contaminantes que estaban
    # por encima del nivel "Bajo" (los que realmente había que tratar).
    necesarios = [c for c in CONT if nivel_de(c, d[c + "_in"]) > 0] or CONT
    ef = round(sum(red[c] for c in necesarios) / len(necesarios), 1)
    d["eficiencia"] = ef
    if ef >= 90:
        d["clasificacion"] = "Excelente"
    elif ef >= 70:
        d["clasificacion"] = "Bueno"
    elif ef >= 40:
        d["clasificacion"] = "Regular"
    else:
        d["clasificacion"] = "Deficiente"
    return d


# ------------------------------------------------------------------ operaciones
def crear(conn, datos, fecha=None):
    v = {}
    for c in CONT:
        try:
            x = float(datos.get(c))
        except (TypeError, ValueError):
            raise ValueError("Valor inválido para " + NOMBRES[c] + ".")
        if not 0 <= x <= MAXIMOS[c]:
            raise ValueError(NOMBRES[c] + " debe estar entre 0 y " + str(MAXIMOS[c]) + ".")
        v[c] = round(x, 1)
    fecha = fecha or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "INSERT INTO procesos(fecha_ingreso,pm25_in,pm10_in,co2_in,co_in) VALUES(?,?,?,?,?)",
        (fecha, v["pm25"], v["pm10"], v["co2"], v["co"]),
    )
    conn.commit()
    return cur.lastrowid


def purificar(conn, pid, filtro, minutos):
    if filtro not in EFICIENCIA:
        raise ValueError("Filtro no válido.")
    try:
        minutos = int(minutos)
    except (TypeError, ValueError):
        raise ValueError("Tiempo inválido.")
    if not 1 <= minutos <= 180:
        raise ValueError("El tiempo debe estar entre 1 y 180 minutos.")
    r = conn.execute("SELECT * FROM procesos WHERE id=?", (pid,)).fetchone()
    if r is None:
        raise ValueError("Proceso no encontrado.")
    if r["pm25_out"] is not None:
        raise ValueError("Este proceso ya fue purificado.")

    ef = EFICIENCIA[filtro]
    ruido = {c: random.uniform(0.97, 1.03) for c in CONT}
    lecturas = []
    for t in range(minutos + 1):
        avance = 1 - math.exp(-3 * t / minutos)  # curva de decaimiento
        fila = {}
        for c in CONT:
            quitado = min(0.999, ef[c] * avance * ruido[c])
            val = r[c + "_in"] * (1 - quitado)
            if c == "co2":  # el CO2 no baja del aire limpio (~420 ppm)
                val = max(val, min(r[c + "_in"], 420))
            fila[c] = round(val, 1)
        lecturas.append((pid, t, fila["pm25"], fila["pm10"], fila["co2"], fila["co"]))
    conn.executemany(
        "INSERT INTO lecturas(proceso_id,minuto,pm25,pm10,co2,co) VALUES(?,?,?,?,?,?)", lecturas
    )
    final = lecturas[-1]
    inicio = datetime.strptime(r["fecha_ingreso"], "%Y-%m-%d %H:%M:%S")
    fin = (inicio + timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE procesos SET filtro=?, minutos=?, fecha_fin=?, "
        "pm25_out=?, pm10_out=?, co2_out=?, co_out=? WHERE id=?",
        (filtro, minutos, fin, final[2], final[3], final[4], final[5], pid),
    )
    conn.commit()


def listar(conn):
    return [enriquecer(r) for r in conn.execute("SELECT * FROM procesos ORDER BY id")]


def detalle(conn, pid):
    r = conn.execute("SELECT * FROM procesos WHERE id=?", (pid,)).fetchone()
    if r is None:
        raise ValueError("Proceso no encontrado.")
    d = enriquecer(r)
    d["lecturas"] = [
        dict(x)
        for x in conn.execute(
            "SELECT minuto,pm25,pm10,co2,co FROM lecturas WHERE proceso_id=? ORDER BY minuto", (pid,)
        )
    ]
    return d


def valores_azar():
    pm25 = round(random.uniform(8, 180), 1)
    if random.random() < 0.3:  # a veces solo hay partículas
        co2, co = round(random.uniform(420, 780)), round(random.uniform(0.5, 3.5), 1)
    else:
        co2, co = round(random.uniform(850, 2800)), round(random.uniform(2, 50), 1)
    return {"pm25": pm25, "pm10": round(pm25 * random.uniform(1.3, 2.2), 1), "co2": co2, "co": co}


def cargar_demo(conn):
    ahora = datetime.now().replace(microsecond=0)
    for i in range(10):
        fecha = (ahora - timedelta(hours=(11 - i) * 5)).strftime("%Y-%m-%d %H:%M:%S")
        pid = crear(conn, valores_azar(), fecha)
        d = enriquecer(conn.execute("SELECT * FROM procesos WHERE id=?", (pid,)).fetchone())
        filtro = d["recomendado"] if random.random() < 0.65 else random.choice(list(EFICIENCIA))
        purificar(conn, pid, filtro, random.choice([5, 8, 10, 15, 20, 30]))
    crear(conn, {"pm25": 140.2, "pm10": 230.5, "co2": 1850, "co": 28.4})  # uno pendiente


def exportar_csv(conn):
    sal = io.StringIO()
    w = csv.writer(sal)
    w.writerow(
        ["ID", "Fecha ingreso", "Nivel ingreso", "Filtro", "Minutos",
         "PM2.5 inicial (ug/m3)", "PM2.5 final", "PM10 inicial (ug/m3)", "PM10 final",
         "CO2 inicial (ppm)", "CO2 final", "CO inicial (ppm)", "CO final",
         "Reduccion PM2.5 %", "Reduccion PM10 %", "Reduccion CO2 %", "Reduccion CO %",
         "Eficiencia %", "Resultado", "Nivel final"]
    )
    for d in listar(conn):
        if d["estado"] == "Purificado":
            r = d["reduccion"]
            w.writerow([d["id"], d["fecha_ingreso"], d["nivel_in"], d["filtro"], d["minutos"],
                        d["pm25_in"], d["pm25_out"], d["pm10_in"], d["pm10_out"],
                        d["co2_in"], d["co2_out"], d["co_in"], d["co_out"],
                        r["pm25"], r["pm10"], r["co2"], r["co"],
                        d["eficiencia"], d["clasificacion"], d["nivel_out"]])
        else:
            w.writerow([d["id"], d["fecha_ingreso"], d["nivel_in"], "", "",
                        d["pm25_in"], "", d["pm10_in"], "", d["co2_in"], "", d["co_in"], "",
                        "", "", "", "", "", "Pendiente", ""])
    return sal.getvalue().encode("utf-8-sig")  # utf-8-sig para que Excel lea las tildes


# ---------------------------------------------------------------------- servidor
class Manejador(BaseHTTPRequestHandler):
    def responder(self, codigo, datos, tipo="application/json; charset=utf-8", extra=None):
        if not isinstance(datos, bytes):
            datos = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(datos)

    def cuerpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def atender(self, metodo):
        ruta = self.path.split("?")[0]
        conn = db()
        try:
            if metodo == "GET" and ruta == "/":
                with open(os.path.join(AQUI, "index.html"), "rb") as f:
                    return self.responder(200, f.read(), "text/html; charset=utf-8")
            if metodo == "GET" and ruta == "/api/config":
                return self.responder(200, {"filtros": list(EFICIENCIA)})
            if metodo == "GET" and ruta == "/api/procesos":
                return self.responder(200, listar(conn))
            if metodo == "GET" and ruta == "/api/reporte.csv":
                return self.responder(200, exportar_csv(conn), "text/csv; charset=utf-8",
                                      {"Content-Disposition": "attachment; filename=reporte_purificacion.csv"})
            if metodo == "POST" and ruta == "/api/procesos":
                pid = crear(conn, self.cuerpo())
                return self.responder(201, detalle(conn, pid))
            if metodo == "POST" and ruta == "/api/demo":
                cargar_demo(conn)
                return self.responder(201, {"ok": True})
            m = re.fullmatch(r"/api/procesos/(\d+)", ruta)
            if m and metodo == "GET":
                return self.responder(200, detalle(conn, int(m.group(1))))
            if m and metodo == "DELETE":
                conn.execute("DELETE FROM lecturas WHERE proceso_id=?", (int(m.group(1)),))
                conn.execute("DELETE FROM procesos WHERE id=?", (int(m.group(1)),))
                conn.commit()
                return self.responder(200, {"ok": True})
            m = re.fullmatch(r"/api/procesos/(\d+)/purificar", ruta)
            if m and metodo == "POST":
                d = self.cuerpo()
                purificar(conn, int(m.group(1)), d.get("filtro"), d.get("minutos"))
                return self.responder(200, detalle(conn, int(m.group(1))))
            return self.responder(404, {"error": "No encontrado"})
        except ValueError as e:
            self.responder(400, {"error": str(e)})
        except Exception as e:  # error inesperado
            self.responder(500, {"error": "Error interno: " + str(e)})
        finally:
            conn.close()

    def do_GET(self):
        self.atender("GET")

    def do_POST(self):
        self.atender("POST")

    def do_DELETE(self):
        self.atender("DELETE")

    def log_message(self, *args):
        pass  # sin ruido en la consola


if __name__ == "__main__":
    iniciar_db()
    url = "http://localhost:%d" % PUERTO
    print("Sistema de purificación de aire funcionando en", url)
    print("Para detenerlo: Ctrl + C")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    HTTPServer(("127.0.0.1", PUERTO), Manejador).serve_forever()
