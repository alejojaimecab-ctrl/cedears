"""
server.py — API Flask para CEDEAR Radar
=========================================
Corre este archivo en tu PC y tu index.html le hace fetch.

Uso:
    pip install flask flask-cors requests
    python server.py

Queda escuchando en http://localhost:5000
"""

import os
import sys
import time
import math
import json
import threading
import requests
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

# ── Importar lógica del bot ───────────────────────────────────────────────────
# server.py tiene que estar en la misma carpeta que cedear_bot.py
sys.path.insert(0, os.path.dirname(__file__))
from cedear_bot import IOLClient, AnalizadorCEDEARs, CEDEARS

# ── Configuración ─────────────────────────────────────────────────────────────
IOL_USER     = os.environ.get("IOL_USER",     "alejojaimecab@gmail.com")
IOL_PASSWORD = os.environ.get("IOL_PASSWORD", "Belgrano1969!")
PORT         = int(os.environ.get("PORT", 5000))

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)   # permite que index.html llame desde cualquier origen

# ── Estado global (se cachea para no re-analizar en cada request) ─────────────
_cache = {
    "datos":      None,   # resultado de analizar_todos()
    "proyecciones": None,
    "timestamp":  None,
    "ccl":        None,
    "analizando": False,
    "error":      None,
}
_lock = threading.Lock()
_iol: IOLClient = None
_analizador: AnalizadorCEDEARs = None


def init_iol():
    """Inicializa el cliente IOL y hace login."""
    global _iol, _analizador
    _iol = IOLClient(IOL_USER, IOL_PASSWORD)
    _iol.login()
    _analizador = AnalizadorCEDEARs(_iol)
    print(f"  ✓ IOL conectado — servidor listo en http://localhost:{PORT}")


def run_analisis(con_proyecciones=False):
    """Ejecuta el análisis en un thread separado para no bloquear Flask."""
    global _cache
    with _lock:
        if _cache["analizando"]:
            return  # ya hay uno corriendo
        _cache["analizando"] = True
        _cache["error"] = None

    try:
        _analizador.analizar_todos()
        if con_proyecciones:
            _analizador.proyecciones()

        with _lock:
            # Serializar resultados (quitar 'raw' que no es JSON-friendly)
            datos_limpios = []
            for r in _analizador.resultados:
                d = {k: v for k, v in r.items() if k != "raw"}
                datos_limpios.append(d)

            _cache["datos"]       = datos_limpios
            _cache["proyecciones"] = getattr(_analizador, "proyecciones_data", [])
            _cache["timestamp"]   = _analizador.timestamp.isoformat() if _analizador.timestamp else None
            _cache["ccl"]         = _analizador.ccl_estimado
            _cache["analizando"]  = False

    except Exception as e:
        with _lock:
            _cache["error"]     = str(e)
            _cache["analizando"] = False
        print(f"  ✗ Error en análisis: {e}")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.route("/api/status")
def status():
    """Estado del servidor y del último análisis."""
    with _lock:
        return jsonify({
            "ok":         True,
            "analizando": _cache["analizando"],
            "timestamp":  _cache["timestamp"],
            "ccl":        _cache["ccl"],
            "error":      _cache["error"],
            "tiene_datos": _cache["datos"] is not None,
        })


@app.route("/api/analizar", methods=["POST"])
def analizar():
    """
    Dispara un análisis nuevo.
    Body JSON opcional: { "proyecciones": true }
    Respuesta inmediata — el análisis corre en background.
    Consultá /api/resultado para ver cuando terminó.
    """
    body = request.get_json(silent=True) or {}
    con_proyecciones = body.get("proyecciones", False)

    with _lock:
        if _cache["analizando"]:
            return jsonify({"ok": False, "mensaje": "Ya hay un análisis en curso"}), 409

    t = threading.Thread(target=run_analisis, args=(con_proyecciones,), daemon=True)
    t.start()
    return jsonify({"ok": True, "mensaje": "Análisis iniciado"})


@app.route("/api/resultado")
def resultado():
    """
    Devuelve el último resultado disponible.
    Si todavía está analizando, devuelve analizando: true y los datos viejos si existen.
    """
    with _lock:
        return jsonify({
            "ok":           True,
            "analizando":   _cache["analizando"],
            "timestamp":    _cache["timestamp"],
            "ccl":          _cache["ccl"],
            "error":        _cache["error"],
            "cedears":      _cache["datos"] or [],
            "proyecciones": _cache["proyecciones"] or [],
        })


@app.route("/api/ticker/<ticker>")
def ticker_detalle(ticker):
    """Cotización y análisis técnico de un CEDEAR puntual."""
    ticker = ticker.upper()
    try:
        if not _analizador.ccl_estimado:
            _analizador.estimar_ccl()
        cot = _analizador.obtener_cotizacion(ticker)
        if not cot:
            return jsonify({"ok": False, "mensaje": f"Sin datos para {ticker}"}), 404

        # Histórico + indicadores desde Yahoo
        cierres = _analizador.obtener_historico_yahoo(ticker, "6mo")
        indicadores = _analizador.calcular_indicadores(cierres) if len(cierres) >= 20 else {}

        # Ratio CCL
        ratio = _analizador.calcular_ratio_ccl(cot["precio"], ticker)

        return jsonify({
            "ok":          True,
            "ticker":      ticker,
            "precio":      cot["precio"],
            "variacion":   cot["variacion"],
            "volumen":     cot["volumen"],
            "apertura":    cot["apertura"],
            "maximo":      cot["maximo"],
            "minimo":      cot["minimo"],
            "ccl":         _analizador.ccl_estimado,
            "ratio_ccl":   ratio,
            "indicadores": indicadores,
        })
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 500


@app.route("/api/sectores")
def sectores():
    """Rendimiento promedio por sector."""
    with _lock:
        datos = _cache["datos"] or []
    if not datos:
        return jsonify({"ok": False, "mensaje": "Sin datos aún"}), 404

    por_sector = {}
    for r in datos:
        s = r["sector"]
        if s not in por_sector:
            por_sector[s] = []
        por_sector[s].append(r["variacion"])

    resultado = []
    for sector, variaciones in sorted(por_sector.items(), key=lambda x: sum(x[1])/len(x[1]), reverse=True):
        prom = sum(variaciones) / len(variaciones)
        tickers = [r["ticker"] for r in datos if r["sector"] == sector]
        resultado.append({
            "sector":    sector,
            "promedio":  round(prom, 2),
            "tickers":   tickers,
            "cantidad":  len(tickers),
        })

    return jsonify({"ok": True, "sectores": resultado})


# ── Arranque ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n  CEDEAR Radar — Servidor API")
    print("  ─────────────────────────────")

    if IOL_USER == "TU_EMAIL_IOL":
        print("  ✗ ERROR: Configurá tus credenciales de IOL")
        print("    export IOL_USER='tu@email.com'")
        print("    export IOL_PASSWORD='tu_password'")
        sys.exit(1)

    try:
        init_iol()
    except Exception as e:
        print(f"  ✗ No se pudo conectar a IOL: {e}")
        sys.exit(1)

    app.run(host="localhost", port=PORT, debug=False)
