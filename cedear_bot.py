"""
CEDEAR Radar Bot — InvertirOnline API
======================================
Analiza CEDEARs del mercado argentino usando la API oficial de IOL.
Muestra ranking en terminal y levanta un dashboard web en localhost.

Uso:
    python cedear_bot.py                  # análisis completo
    python cedear_bot.py --solo-terminal  # solo consola, sin web
    python cedear_bot.py --ticker AAPL    # analiza un CEDEAR puntual
"""

import requests
import json
import time
import argparse
import os
import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

# ─────────────────────────────────────────────
#  CONFIGURACIÓN — editá estos valores
# ─────────────────────────────────────────────
IOL_USER     = os.environ.get("IOL_USER", "TU_EMAIL_IOL")
IOL_PASSWORD = os.environ.get("IOL_PASSWORD", "TU_PASSWORD_IOL")
DASHBOARD_PORT = 8080

# CEDEARs a monitorear (los más operados en Argentina)
CEDEARS = {
    "Tecnología":  ["AAPL",  "MSFT",  "GOOGL", "AMZN",  "META",  "TSLA",  "NVDA",  "MELI",  "GLOB"],
    "Energía":     ["XOM",   "CVX",   "OXY",   "SLB",   "COP"],
    "Bancos":      ["JPM",   "BAC",   "GS",    "BRK/B", "C"],
    "Consumo":     ["WMT",   "COST",  "MCD",   "KO",    "NKE",   "PEP"],
    "Salud":       ["JNJ",   "PFE",   "ABBV",  "MRK"],
    "ETFs":        ["SPY",   "QQQ",   "GLD"],
}
TODOS_LOS_TICKERS = [t for lista in CEDEARS.values() for t in lista]

# ─────────────────────────────────────────────
#  COLORES PARA TERMINAL (ANSI)
# ─────────────────────────────────────────────
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    WHITE  = "\033[97m"
    GRAY   = "\033[90m"
    BG_DARK = "\033[40m"

def verde(t):  return f"{C.GREEN}{t}{C.RESET}"
def rojo(t):   return f"{C.RED}{t}{C.RESET}"
def amarillo(t): return f"{C.YELLOW}{t}{C.RESET}"
def cyan(t):   return f"{C.CYAN}{t}{C.RESET}"
def negrita(t): return f"{C.BOLD}{t}{C.RESET}"
def gris(t):   return f"{C.GRAY}{t}{C.RESET}"

# ─────────────────────────────────────────────
#  CLIENTE IOL API
# ─────────────────────────────────────────────
class IOLClient:
    BASE = "https://api.invertironline.com"

    def __init__(self, usuario, password):
        self.usuario  = usuario
        self.password = password
        self.token    = None
        self.refresh_token = None
        self.token_expiry  = 0

    def login(self):
        """Obtiene token de acceso."""
        print(gris("  → Autenticando con IOL..."))
        r = requests.post(
            f"{self.BASE}/token",
            data={
                "username": self.usuario,
                "password": self.password,
                "grant_type": "password",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15
        )
        if r.status_code != 200:
            raise Exception(f"Login fallido ({r.status_code}): {r.text}")
        data = r.json()
        self.token         = data["access_token"]
        self.refresh_token = data.get("refresh_token")
        self.token_expiry  = time.time() + data.get("expires_in", 1800) - 60
        print(verde("  ✓ Autenticado correctamente"))
        return self.token

    def _refresh(self):
        """Renueva el token si está por vencer."""
        r = requests.post(
            f"{self.BASE}/token",
            data={
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            self.token        = data["access_token"]
            self.token_expiry = time.time() + data.get("expires_in", 1800) - 60

    def _headers(self):
        if time.time() > self.token_expiry:
            self._refresh()
        return {"Authorization": f"Bearer {self.token}"}

    def cotizacion(self, ticker):
        """Cotización de un CEDEAR en BYMA."""
        # IOL endpoint para cotización de instrumento
        url = f"{self.BASE}/api/v2/Cotizaciones/cedears/{ticker}/ultimo"
        r = requests.get(url, headers=self._headers(), timeout=10)
        if r.status_code == 200:
            return r.json()
        # Fallback: endpoint alternativo
        url2 = f"{self.BASE}/api/v2/Cotizaciones/BCBA/{ticker}/ultimo"
        r2 = requests.get(url2, headers=self._headers(), timeout=10)
        if r2.status_code == 200:
            return r2.json()
        return None

    def portafolio(self):
        """Devuelve el portafolio del usuario (opcional)."""
        r = requests.get(
            f"{self.BASE}/api/v2/portafolio/argentina",
            headers=self._headers(), timeout=10
        )
        return r.json() if r.status_code == 200 else None

    def dolar_ccl(self):
        """Intenta obtener el dólar CCL/MEP desde IOL (GD30D / AL30D)."""
        # GD30D / AL30D son los bonos referencia para calcular CCL
        try:
            gd30 = self.cotizacion("GD30")
            al30 = self.cotizacion("AL30")
            return {"GD30": gd30, "AL30": al30}
        except:
            return {}

# ─────────────────────────────────────────────
#  MOTOR DE ANÁLISIS
# ─────────────────────────────────────────────
class AnalizadorCEDEARs:

    def __init__(self, iol: IOLClient):
        self.iol = iol
        self.resultados = []
        self.timestamp  = None
        self.ccl_estimado = None
        self.proyecciones_data = []

    def obtener_cotizacion(self, ticker):
        """Procesa la cotización de IOL y extrae los campos clave."""
        raw = self.iol.cotizacion(ticker)
        if not raw:
            return None
        try:
            # La API de IOL puede devolver distintas estructuras según versión
            precio = (
                raw.get("ultimoPrecio") or
                raw.get("ultimo") or
                raw.get("cotizacion", {}).get("ultimo") or
                0
            )
            variacion_pct = (
                raw.get("variacion") or
                raw.get("variacionPorcentual") or
                raw.get("cotizacion", {}).get("variacion") or
                0
            )
            volumen = (
                raw.get("volumen") or
                raw.get("cantidadOperada") or
                0
            )
            apertura = raw.get("apertura") or raw.get("precioApertura") or 0
            maximo   = raw.get("maximo") or raw.get("precioMaximo") or precio
            minimo   = raw.get("minimo") or raw.get("precioMinimo") or precio

            return {
                "ticker":    ticker,
                "precio":    float(precio),
                "variacion": float(variacion_pct),
                "volumen":   float(volumen),
                "apertura":  float(apertura),
                "maximo":    float(maximo),
                "minimo":    float(minimo),
                "raw":       raw,
            }
        except Exception as e:
            return None

    def calcular_ratio_ccl(self, precio_ars, ticker_usd=None):
        """
        Ratio = precio_ars / (precio_usd_subyacente × ccl)
        Si no tenemos el precio USD real, usamos una estimación.
        < 0.95 = descuento (barato)
        0.95-1.05 = precio justo
        > 1.05 = prima (caro)
        """
        if not self.ccl_estimado or not ticker_usd:
            return None
        try:
            # precio_usd aproximado desde Yahoo Finance (fallback HTTP)
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_usd}",
                params={"interval": "1d", "range": "1d"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=8
            )
            if r.status_code == 200:
                data = r.json()
                precio_usd = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
                ratio = precio_ars / (precio_usd * self.ccl_estimado)
                return round(ratio, 3)
        except:
            pass
        return None

    def estimar_ccl(self):
        """Estima el dólar CCL con datos públicos (bluelytics o dolarapi)."""
        fuentes = [
            ("https://dolarapi.com/v1/dolares/contadoconliqui", "venta"),
            ("https://dolarapi.com/v1/dolares/bolsa", "venta"),
        ]
        for url, campo in fuentes:
            try:
                r = requests.get(url, timeout=6)
                if r.status_code == 200:
                    data = r.json()
                    val = data.get(campo) or data.get("venta")
                    if val:
                        self.ccl_estimado = float(val)
                        return float(val)
            except:
                continue

        # Último fallback: bluelytics
        try:
            r = requests.get("https://api.bluelytics.com.ar/v2/latest", timeout=6)
            if r.status_code == 200:
                data = r.json()
                self.ccl_estimado = float(data["blue"]["value_sell"])
                return self.ccl_estimado
        except:
            pass

        self.ccl_estimado = 1250  # fallback hardcoded si todo falla
        return self.ccl_estimado

    def analizar_todos(self):
        """Descarga cotizaciones de todos los CEDEARs y arma el ranking."""
        print(f"\n{cyan('─'*55)}")
        print(f"  {negrita('CEDEAR RADAR')} — Analizando mercado argentino")
        print(f"  {gris(datetime.now().strftime('%d/%m/%Y %H:%M:%S'))}")
        print(f"{cyan('─'*55)}\n")

        print(gris("  → Obteniendo tipo de cambio CCL..."))
        ccl = self.estimar_ccl()
        print(f"  Dólar CCL estimado: {verde('$' + f'{ccl:,.0f}')}\n")

        resultados = []
        errores = []

        print(gris(f"  → Descargando cotizaciones de {len(TODOS_LOS_TICKERS)} CEDEARs...\n"))

        for sector, tickers in CEDEARS.items():
            for ticker in tickers:
                try:
                    cot = self.obtener_cotizacion(ticker)
                    if cot and cot["precio"] > 0:
                        cot["sector"] = sector
                        resultados.append(cot)
                        signo = "▲" if cot["variacion"] >= 0 else "▼"
                        color = verde if cot["variacion"] >= 0 else rojo
                        var_str = color(f"{signo} {cot['variacion']:+.2f}%")
                        print(f"  {ticker:<8} {var_str:<20} ${cot['precio']:>10,.2f} ARS   {gris(sector)}")
                    else:
                        errores.append(ticker)
                        print(f"  {ticker:<8} {gris('sin datos')}")
                    time.sleep(0.15)  # rate limiting suave
                except Exception as e:
                    errores.append(ticker)
                    print(f"  {ticker:<8} {rojo(f'error: {str(e)[:30]}')}")

        self.resultados = sorted(resultados, key=lambda x: x["variacion"], reverse=True)
        self.timestamp  = datetime.now()

        if errores:
            print(f"\n{amarillo(f'  ⚠ Sin datos para: {', '.join(errores)}')}")

        return self.resultados

    def analizar_ticker(self, ticker):
        """Análisis detallado de un CEDEAR puntual."""
        ticker = ticker.upper()
        print(f"\n{cyan('─'*55)}")
        print(f"  Análisis detallado: {negrita(ticker)}")
        print(f"{cyan('─'*55)}\n")

        ccl = self.estimar_ccl()
        cot = self.obtener_cotizacion(ticker)

        if not cot:
            print(rojo(f"  ✗ No se encontraron datos para {ticker}"))
            return

        v = cot["variacion"]
        p = cot["precio"]
        color = verde if v >= 0 else rojo
        signo = "▲" if v >= 0 else "▼"

        print(f"  Ticker:     {negrita(ticker)}")
        print(f"  Precio:     {negrita(f'${p:,.2f} ARS')}")
        print(f"  Variación:  {color(f'{signo} {v:+.2f}%')}")
        print(f"  Apertura:   ${cot['apertura']:,.2f}")
        print(f"  Máximo:     ${cot['maximo']:,.2f}")
        print(f"  Mínimo:     ${cot['minimo']:,.2f}")
        print(f"  Volumen:    {cot['volumen']:,.0f}")
        print(f"  Dólar CCL:  ${ccl:,.0f}")

        ratio = self.calcular_ratio_ccl(p, ticker)
        if ratio:
            if ratio < 0.95:
                estado = verde(f"{ratio:.3f}x — DESCUENTO ✓ (posible oportunidad)")
            elif ratio > 1.05:
                estado = rojo(f"{ratio:.3f}x — PRIMA ✗ (cotiza más caro que el subyacente)")
            else:
                estado = amarillo(f"{ratio:.3f}x — PRECIO JUSTO")
            print(f"  Ratio CCL:  {estado}")

        # Señal simple basada en momentum
        señal = _señal_momentum(cot)
        print(f"\n  Señal técnica: {señal}")

    def imprimir_ranking(self, top_n=10):
        """Imprime el ranking en la terminal."""
        if not self.resultados:
            print(rojo("  No hay datos. Ejecutá analizar_todos() primero."))
            return

        print(f"\n{cyan('═'*55)}")
        print(f"  🏆 TOP {top_n} CEDEARs — Mejor rendimiento")
        print(f"{cyan('═'*55)}\n")

        print(f"  {'#':<3} {'TICKER':<8} {'VARIACIÓN':>10} {'PRECIO ARS':>12} {'SECTOR'}")
        print(f"  {gris('─'*50)}")

        for i, r in enumerate(self.resultados[:top_n], 1):
            v    = r["variacion"]
            p    = r["precio"]
            color = verde if v >= 0 else rojo
            signo = "▲" if v >= 0 else "▼"
            print(f"  {str(i)+'.':<3} {negrita(r['ticker']):<8} "
                  f"{color(f'{signo} {v:+.2f}%'):>10}   "
                  f"${p:>10,.2f}   {gris(r['sector'])}")

        print(f"\n{cyan('─'*55)}")
        print(f"  📉 PEORES 5 del día")
        print(f"{cyan('─'*55)}\n")

        for r in self.resultados[-5:]:
            v = r["variacion"]
            print(f"  {r['ticker']:<8} {rojo(f'▼ {v:+.2f}%'):>10}   ${r['precio']:>10,.2f}   {gris(r['sector'])}")

        print(f"\n{cyan('─'*55)}")
        print(f"  🏭 Rendimiento promedio por sector")
        print(f"{cyan('─'*55)}\n")

        por_sector = {}
        for r in self.resultados:
            s = r["sector"]
            if s not in por_sector:
                por_sector[s] = []
            por_sector[s].append(r["variacion"])

        sector_prom = {s: sum(v)/len(v) for s, v in por_sector.items()}
        for s, prom in sorted(sector_prom.items(), key=lambda x: x[1], reverse=True):
            color = verde if prom >= 0 else rojo
            bar = "█" * min(int(abs(prom) * 3), 20)
            print(f"  {s:<15} {color(f'{prom:+.2f}%'):>10}  {color(bar)}")

        print(f"\n{gris('  Actualizado: ' + self.timestamp.strftime('%d/%m/%Y %H:%M:%S'))}\n")

    def oportunidades(self):
        """CEDEARs con mejor relación riesgo/retorno según momentum y volumen."""
        print(f"\n{cyan('═'*55)}")
        print(f"  ⭐ RADAR DE OPORTUNIDADES")
        print(f"{cyan('═'*55)}\n")

        candidatos = [r for r in self.resultados if r["variacion"] > 0 and r["volumen"] > 0]
        import math
        scored = sorted(candidatos, key=lambda x: x["variacion"] * math.log(x["volumen"]+1), reverse=True)

        for i, r in enumerate(scored[:5], 1):
            señal = _señal_momentum(r)
            label = negrita(f"{i}. {r['ticker']}")
            var   = verde(f"+{r['variacion']:.2f}%")
            print(f"  {label:<15} {var}")
            print(f"  {gris(r['sector'])} | Vol: {r['volumen']:,.0f} | {señal}")
            print()

    # ─────────────────────────────────────────────
    #  PROYECCIONES CORTO Y LARGO PLAZO
    # ─────────────────────────────────────────────

    def obtener_historico_yahoo(self, ticker, periodo="6mo"):
        """
        Descarga precios históricos desde Yahoo Finance.
        periodo: '1mo' | '3mo' | '6mo' | '1y' | '2y'
        Devuelve lista de cierres diarios (float) o [] si falla.
        """
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            params = {"interval": "1d", "range": periodo}
            r = requests.get(url, params=params,
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if r.status_code != 200:
                return []
            data  = r.json()
            cierres = data["chart"]["result"][0]["indicators"]["quote"][0].get("close", [])
            # Filtramos None
            return [float(c) for c in cierres if c is not None]
        except:
            return []

    def calcular_indicadores(self, cierres):
        """
        Calcula indicadores técnicos sobre una lista de cierres.
        Retorna dict con: sma20, sma50, sma200, rsi14, bb_upper, bb_lower,
                          tendencia_corto, tendencia_largo, score_corto, score_largo
        """
        import math

        def sma(datos, n):
            if len(datos) < n:
                return None
            return sum(datos[-n:]) / n

        def rsi(datos, n=14):
            if len(datos) < n + 1:
                return None
            ganancias, perdidas = [], []
            for i in range(1, n + 1):
                diff = datos[-(n + 1 - i) + 1 + i - 1] - datos[-(n + 1 - i) + i - 1] if i > 0 else 0
                cambio = datos[-n + i] - datos[-n + i - 1]
                if cambio > 0:
                    ganancias.append(cambio); perdidas.append(0)
                else:
                    ganancias.append(0); perdidas.append(abs(cambio))
            avg_g = sum(ganancias) / n
            avg_p = sum(perdidas) / n
            if avg_p == 0:
                return 100.0
            rs = avg_g / avg_p
            return round(100 - (100 / (1 + rs)), 2)

        def bollinger(datos, n=20, k=2):
            if len(datos) < n:
                return None, None
            ventana = datos[-n:]
            media = sum(ventana) / n
            std   = math.sqrt(sum((x - media) ** 2 for x in ventana) / n)
            return round(media + k * std, 4), round(media - k * std, 4)

        precio_actual = cierres[-1] if cierres else None
        s20  = sma(cierres, 20)
        s50  = sma(cierres, 50)
        s200 = sma(cierres, 200)
        rsi_val = rsi(cierres, 14)
        bb_up, bb_lo = bollinger(cierres, 20)

        # ── Score corto plazo (0–100) ──────────────────────────────────────
        # Señales: precio vs SMA20, precio vs BB, RSI, momentum 5 días
        score_cp = 50  # neutro de base
        señales_cp = []

        if precio_actual and s20:
            if precio_actual > s20:
                score_cp += 10
                señales_cp.append("precio > SMA20 ✓")
            else:
                score_cp -= 10
                señales_cp.append("precio < SMA20 ✗")

        if precio_actual and s50:
            if precio_actual > s50:
                score_cp += 8
                señales_cp.append("precio > SMA50 ✓")
            else:
                score_cp -= 8

        if rsi_val:
            if 40 <= rsi_val <= 60:
                score_cp += 5
                señales_cp.append(f"RSI neutro ({rsi_val:.0f})")
            elif rsi_val < 35:
                score_cp += 12   # sobreventa → rebote potencial
                señales_cp.append(f"RSI sobreventa ({rsi_val:.0f}) — rebote potencial ✓")
            elif rsi_val > 70:
                score_cp -= 12   # sobrecompra → posible corrección
                señales_cp.append(f"RSI sobrecompra ({rsi_val:.0f}) — precaución ✗")
            elif rsi_val >= 50:
                score_cp += 8
                señales_cp.append(f"RSI positivo ({rsi_val:.0f}) ✓")

        if precio_actual and bb_lo and bb_up:
            rango_bb = bb_up - bb_lo
            if rango_bb > 0:
                pos_bb = (precio_actual - bb_lo) / rango_bb
                if pos_bb < 0.2:
                    score_cp += 10
                    señales_cp.append("cerca de BB inferior — posible rebote ✓")
                elif pos_bb > 0.85:
                    score_cp -= 8
                    señales_cp.append("cerca de BB superior — posible resistencia ✗")

        # Momentum 5 días
        if len(cierres) >= 6:
            mom5 = (cierres[-1] / cierres[-6] - 1) * 100
            if mom5 > 3:
                score_cp += 10
                señales_cp.append(f"momentum 5d: +{mom5:.1f}% ✓")
            elif mom5 < -3:
                score_cp -= 10
                señales_cp.append(f"momentum 5d: {mom5:.1f}% ✗")

        score_cp = max(0, min(100, score_cp))

        # ── Score largo plazo (0–100) ──────────────────────────────────────
        # Señales: SMA50 vs SMA200 (Golden/Death Cross), tendencia 6m, RSI estructural
        score_lp = 50
        señales_lp = []

        if s50 and s200:
            if s50 > s200:
                score_lp += 20
                señales_lp.append("Golden Cross SMA50 > SMA200 ✓")
            else:
                score_lp -= 20
                señales_lp.append("Death Cross SMA50 < SMA200 ✗")

        if precio_actual and s200:
            if precio_actual > s200:
                score_lp += 15
                señales_lp.append("precio sobre SMA200 (tendencia alcista) ✓")
            else:
                score_lp -= 15
                señales_lp.append("precio bajo SMA200 (tendencia bajista) ✗")

        # Tendencia 3 meses
        if len(cierres) >= 60:
            tend3m = (cierres[-1] / cierres[-60] - 1) * 100
            if tend3m > 10:
                score_lp += 12
                señales_lp.append(f"tendencia 3m: +{tend3m:.1f}% ✓")
            elif tend3m > 0:
                score_lp += 5
                señales_lp.append(f"tendencia 3m: +{tend3m:.1f}%")
            elif tend3m < -10:
                score_lp -= 12
                señales_lp.append(f"tendencia 3m: {tend3m:.1f}% ✗")
            else:
                score_lp -= 5

        if rsi_val:
            if rsi_val >= 50:
                score_lp += 8
                señales_lp.append(f"RSI estructural positivo ({rsi_val:.0f}) ✓")
            else:
                score_lp -= 5

        score_lp = max(0, min(100, score_lp))

        # Etiquetas
        def etiqueta(score):
            if score >= 75: return "MUY ALCISTA 🚀"
            if score >= 60: return "ALCISTA 📈"
            if score >= 45: return "NEUTRAL ➡"
            if score >= 30: return "BAJISTA 📉"
            return "MUY BAJISTA ⚠"

        return {
            "precio":         precio_actual,
            "sma20":          round(s20, 2) if s20 else None,
            "sma50":          round(s50, 2) if s50 else None,
            "sma200":         round(s200, 2) if s200 else None,
            "rsi14":          rsi_val,
            "bb_upper":       bb_up,
            "bb_lower":       bb_lo,
            "score_corto":    score_cp,
            "score_largo":    score_lp,
            "label_corto":    etiqueta(score_cp),
            "label_largo":    etiqueta(score_lp),
            "señales_corto":  señales_cp,
            "señales_largo":  señales_lp,
        }

    def proyecciones(self, top_n=8):
        """
        Analiza proyecciones de corto plazo (días/semanas) y largo plazo (meses)
        para todos los CEDEARs con datos disponibles.
        Imprime ranking separado para cada horizonte.
        Guarda resultados en self.proyecciones_data para el dashboard.
        """
        if not self.resultados:
            print(rojo("  No hay datos. Ejecutá analizar_todos() primero."))
            return

        print(f"\n{cyan('═'*60)}")
        print(f"  🔮 PROYECCIONES — Corto y Largo Plazo")
        print(f"  {gris('Indicadores: SMA20/50/200 · RSI14 · Bollinger Bands')}")
        print(f"{cyan('═'*60)}\n")
        print(gris("  → Descargando históricos desde Yahoo Finance (6 meses)...\n"))

        scored = []
        total = len(self.resultados)

        for i, r in enumerate(self.resultados, 1):
            ticker = r["ticker"]
            print(f"  {gris(f'[{i}/{total}]')} {ticker:<8}", end="", flush=True)
            cierres = self.obtener_historico_yahoo(ticker, "6mo")
            if len(cierres) < 20:
                print(gris("  sin histórico suficiente"))
                time.sleep(0.1)
                continue
            indicadores = self.calcular_indicadores(cierres)
            indicadores["ticker"]  = ticker
            indicadores["sector"]  = r["sector"]
            indicadores["variacion_hoy"] = r["variacion"]
            scored.append(indicadores)
            print(f"  CP:{indicadores['score_corto']:>3}/100  LP:{indicadores['score_largo']:>3}/100  "
                  f"{amarillo(indicadores['label_corto'])}")
            time.sleep(0.12)

        if not scored:
            print(rojo("\n  ✗ No se pudieron obtener históricos."))
            return

        # Guardar para el dashboard
        self.proyecciones_data = scored

        # ── RANKING CORTO PLAZO ────────────────────────────────────────────
        top_cp = sorted(scored, key=lambda x: x["score_corto"], reverse=True)

        print(f"\n{cyan('─'*60)}")
        print(f"  📅 CORTO PLAZO — Próximos días / semanas")
        print(f"  {gris('Score basado en: RSI · Bollinger · SMA20 · Momentum 5d')}")
        print(f"{cyan('─'*60)}\n")
        print(f"  {'#':<3} {'TICKER':<8} {'SCORE':>7} {'SEÑAL':<22} {'SECTOR'}")
        print(f"  {gris('─'*55)}")

        for i, ind in enumerate(top_cp[:top_n], 1):
            score = ind["score_corto"]
            barra = _barra_score(score)
            label = ind["label_corto"]
            color = _color_score(score)
            print(f"  {str(i)+'.':<3} {negrita(ind['ticker']):<8} "
                  f"{color(f'{score:>3}/100')}  {barra}  {color(label):<22}  {gris(ind['sector'])}")

        print(f"\n  {gris('Detalle top 3:')}\n")
        for ind in top_cp[:3]:
            print(f"  {negrita(ind['ticker'])} — Score CP: {_color_score(ind['score_corto'])(str(ind['score_corto']))}/100")
            if ind.get("sma20"):
                print(f"    SMA20: ${ind['sma20']:,.2f}  |  SMA50: ${ind['sma50']:,.2f}" if ind.get("sma50")
                      else f"    SMA20: ${ind['sma20']:,.2f}")
            if ind.get("rsi14"):
                print(f"    RSI14: {ind['rsi14']:.1f}")
            if ind.get("bb_upper") and ind.get("bb_lower"):
                print(f"    Bollinger: ${ind['bb_lower']:,.2f} — ${ind['bb_upper']:,.2f}")
            for s in ind.get("señales_corto", []):
                print(f"    {gris('·')} {s}")
            print()

        # ── RANKING LARGO PLAZO ────────────────────────────────────────────
        top_lp = sorted(scored, key=lambda x: x["score_largo"], reverse=True)

        print(f"{cyan('─'*60)}")
        print(f"  📆 LARGO PLAZO — Próximos meses")
        print(f"  {gris('Score basado en: Golden/Death Cross · SMA200 · Tendencia 3m · RSI')}")
        print(f"{cyan('─'*60)}\n")
        print(f"  {'#':<3} {'TICKER':<8} {'SCORE':>7} {'SEÑAL':<22} {'SECTOR'}")
        print(f"  {gris('─'*55)}")

        for i, ind in enumerate(top_lp[:top_n], 1):
            score = ind["score_largo"]
            barra = _barra_score(score)
            label = ind["label_largo"]
            color = _color_score(score)
            print(f"  {str(i)+'.':<3} {negrita(ind['ticker']):<8} "
                  f"{color(f'{score:>3}/100')}  {barra}  {color(label):<22}  {gris(ind['sector'])}")

        print(f"\n  {gris('Detalle top 3:')}\n")
        for ind in top_lp[:3]:
            print(f"  {negrita(ind['ticker'])} — Score LP: {_color_score(ind['score_largo'])(str(ind['score_largo']))}/100")
            if ind.get("sma50") and ind.get("sma200"):
                cross = "Golden Cross ✓" if ind["sma50"] > ind["sma200"] else "Death Cross ✗"
                cross_color = verde if ind["sma50"] > ind["sma200"] else rojo
                print(f"    {cross_color(cross)}  |  SMA50: ${ind['sma50']:,.2f}  |  SMA200: ${ind['sma200']:,.2f}")
            if ind.get("rsi14"):
                print(f"    RSI14: {ind['rsi14']:.1f}")
            for s in ind.get("señales_largo", []):
                print(f"    {gris('·')} {s}")
            print()

        # ── MATRIZ COMBINADA ───────────────────────────────────────────────
        print(f"{cyan('─'*60)}")
        print(f"  🎯 MATRIZ COMBINADA — Mejor en ambos horizontes")
        print(f"{cyan('─'*60)}\n")

        combinados = sorted(scored, key=lambda x: x["score_corto"] + x["score_largo"], reverse=True)
        print(f"  {'TICKER':<8} {'CORTO':>8} {'LARGO':>8} {'COMBINADO':>11}  {'VEREDICTO'}")
        print(f"  {gris('─'*55)}")
        for ind in combinados[:6]:
            sc = ind["score_corto"]
            sl = ind["score_largo"]
            comb = sc + sl
            if comb >= 140:
                veredicto = verde("⭐ MUY RECOMENDADO")
            elif comb >= 110:
                veredicto = verde("✓ RECOMENDADO")
            elif comb >= 80:
                veredicto = amarillo("~ NEUTRAL")
            else:
                veredicto = rojo("✗ PRECAUCIÓN")
            print(f"  {negrita(ind['ticker']):<8} {_color_score(sc)(f'{sc:>3}/100')}   "
                  f"{_color_score(sl)(f'{sl:>3}/100')}   {str(comb):>5}/200   {veredicto}")

        print(f"\n{gris('  Nota: scores basados en indicadores técnicos de precios USD (subyacente).')}")
        print(gris("  No incluyen análisis fundamental ni contexto macro argentino específico.\n"))


def _señal_momentum(cot):
    """Señal simple basada en posición del precio dentro del rango diario."""
    try:
        rango = cot["maximo"] - cot["minimo"]
        if rango == 0:
            return amarillo("NEUTRAL")
        pos = (cot["precio"] - cot["minimo"]) / rango
        if pos > 0.8:
            return verde("MOMENTUM ALCISTA 🟢")
        elif pos < 0.2:
            return rojo("MOMENTUM BAJISTA 🔴")
        else:
            return amarillo("LATERAL / CONSOLIDANDO 🟡")
    except:
        return gris("N/D")


def _barra_score(score, ancho=12):
    """Barra visual proporcional al score (0-100)."""
    llenos = int(score / 100 * ancho)
    vacios = ancho - llenos
    if score >= 65:
        color = C.GREEN
    elif score >= 45:
        color = C.YELLOW
    else:
        color = C.RED
    return f"{color}{'█' * llenos}{'░' * vacios}{C.RESET}"


def _color_score(score):
    """Devuelve función de color según score."""
    if score >= 65:
        return verde
    elif score >= 45:
        return amarillo
    else:
        return rojo


# ─────────────────────────────────────────────
#  DASHBOARD WEB (localhost)
# ─────────────────────────────────────────────
def generar_html(analizador: AnalizadorCEDEARs) -> str:
    """Genera el HTML del dashboard con los datos actuales."""
    ts = analizador.timestamp.strftime("%d/%m/%Y %H:%M:%S") if analizador.timestamp else "—"
    ccl = f"${analizador.ccl_estimado:,.0f}" if analizador.ccl_estimado else "N/D"

    rows_top = ""
    for i, r in enumerate(analizador.resultados[:15], 1):
        v = r["variacion"]
        color = "#00e5a0" if v >= 0 else "#ef4444"
        signo = "▲" if v >= 0 else "▼"
        rows_top += f"""
        <tr>
          <td style="color:#666">{i}</td>
          <td><strong style="font-size:15px">{r['ticker']}</strong></td>
          <td style="color:{color};font-weight:700">{signo} {v:+.2f}%</td>
          <td>${r['precio']:,.2f}</td>
          <td style="color:#666;font-size:11px">{r['sector']}</td>
          <td style="color:#aaa">{r['volumen']:,.0f}</td>
        </tr>"""

    # Sectores
    import math
    por_sector = {}
    for r in analizador.resultados:
        s = r["sector"]
        if s not in por_sector:
            por_sector[s] = []
        por_sector[s].append(r["variacion"])
    sector_cards = ""
    for s, vals in sorted(por_sector.items(), key=lambda x: sum(x[1])/len(x[1]), reverse=True):
        prom = sum(vals)/len(vals)
        color = "#00e5a0" if prom >= 0 else "#ef4444"
        tickers_s = [r["ticker"] for r in analizador.resultados if r["sector"] == s][:4]
        sector_cards += f"""
        <div style="background:#1a1a24;border:1px solid #2a2a3a;padding:16px;border-radius:4px;border-top:3px solid {color}">
          <div style="font-size:11px;color:#666;letter-spacing:2px;margin-bottom:6px">{s.upper()}</div>
          <div style="font-size:24px;font-weight:800;color:{color}">{prom:+.2f}%</div>
          <div style="font-size:10px;color:#555;margin-top:8px">{' · '.join(tickers_s)}</div>
        </div>"""

    # ── Sección proyecciones (si hay datos) ──────────────────────────────
    seccion_proyecciones = ""
    proy = getattr(analizador, "proyecciones_data", None)
    if proy:
        # Tabla corto plazo
        top_cp = sorted(proy, key=lambda x: x["score_corto"], reverse=True)[:8]
        top_lp = sorted(proy, key=lambda x: x["score_largo"], reverse=True)[:8]
        combinados = sorted(proy, key=lambda x: x["score_corto"] + x["score_largo"], reverse=True)[:6]

        def score_color(s):
            if s >= 65: return "#00e5a0"
            if s >= 45: return "#f59e0b"
            return "#ef4444"

        def score_bar_html(s, ancho=80):
            pct = s
            c = score_color(s)
            return f'<div style="background:#1a1a24;border-radius:2px;height:6px;width:{ancho}px;display:inline-block;vertical-align:middle;margin-left:8px"><div style="background:{c};height:6px;width:{int(pct*ancho/100)}px;border-radius:2px"></div></div>'

        def rows_proy(lista, campo_score, campo_label):
            html = ""
            for i, ind in enumerate(lista, 1):
                sc = ind[campo_score]
                c  = score_color(sc)
                html += f"""<tr>
                  <td style="color:#666">{i}</td>
                  <td><strong style="font-size:14px">{ind['ticker']}</strong></td>
                  <td style="color:{c};font-weight:700">{sc}/100{score_bar_html(sc)}</td>
                  <td style="color:{c};font-size:11px">{ind[campo_label]}</td>
                  <td style="color:#555;font-size:11px">{ind.get('rsi14', '—')}</td>
                  <td style="color:#555;font-size:11px">{ind['sector']}</td>
                </tr>"""
            return html

        rows_cp   = rows_proy(top_cp, "score_corto", "label_corto")
        rows_lp   = rows_proy(top_lp, "score_largo", "label_largo")

        comb_rows = ""
        for ind in combinados:
            sc = ind["score_corto"]; sl = ind["score_largo"]; comb = sc + sl
            c  = "#00e5a0" if comb >= 140 else "#f59e0b" if comb >= 110 else "#ef4444"
            veredicto = "⭐ MUY RECOMENDADO" if comb >= 140 else "✓ RECOMENDADO" if comb >= 110 else "~ NEUTRAL" if comb >= 80 else "✗ PRECAUCIÓN"
            comb_rows += f"""<tr>
              <td><strong>{ind['ticker']}</strong></td>
              <td style="color:{score_color(sc)}">{sc}/100</td>
              <td style="color:{score_color(sl)}">{sl}/100</td>
              <td style="color:{c};font-weight:700">{comb}/200</td>
              <td style="color:{c}">{veredicto}</td>
              <td style="color:#555;font-size:11px">{ind['sector']}</td>
            </tr>"""

        seccion_proyecciones = f"""
  <div style="margin-top:20px">
    <div style="font-size:11px;color:#7c3aed;letter-spacing:3px;margin-bottom:12px">// PROYECCIONES TÉCNICAS</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">

      <div class="card" style="border-top:2px solid #00e5a0">
        <div style="font-size:11px;color:#00e5a0;letter-spacing:2px;margin-bottom:12px">📅 CORTO PLAZO (días / semanas)</div>
        <div style="font-size:10px;color:#444;margin-bottom:10px">RSI · Bollinger · SMA20 · Momentum 5d</div>
        <table><thead><tr>
          <th>#</th><th>TICKER</th><th>SCORE</th><th>SEÑAL</th><th>RSI</th><th>SECTOR</th>
        </tr></thead><tbody>{rows_cp}</tbody></table>
      </div>

      <div class="card" style="border-top:2px solid #7c3aed">
        <div style="font-size:11px;color:#a78bfa;letter-spacing:2px;margin-bottom:12px">📆 LARGO PLAZO (meses)</div>
        <div style="font-size:10px;color:#444;margin-bottom:10px">Golden/Death Cross · SMA200 · Tendencia 3m</div>
        <table><thead><tr>
          <th>#</th><th>TICKER</th><th>SCORE</th><th>SEÑAL</th><th>RSI</th><th>SECTOR</th>
        </tr></thead><tbody>{rows_lp}</tbody></table>
      </div>
    </div>

    <div class="card" style="border-top:2px solid #f59e0b">
      <div style="font-size:11px;color:#f59e0b;letter-spacing:2px;margin-bottom:12px">🎯 MATRIZ COMBINADA — Mejor en ambos horizontes</div>
      <table><thead><tr>
        <th>TICKER</th><th>CORTO</th><th>LARGO</th><th>TOTAL</th><th>VEREDICTO</th><th>SECTOR</th>
      </tr></thead><tbody>{comb_rows}</tbody></table>
    </div>

    <div style="font-size:10px;color:#333;margin-top:10px">
      Scores técnicos calculados sobre precios USD del subyacente (Yahoo Finance). No incluyen análisis fundamental ni contexto macro local.
    </div>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="300">
<title>CEDEAR Radar</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@700;800&display=swap" rel="stylesheet">
<style>
  * {{ margin:0;padding:0;box-sizing:border-box }}
  body {{ background:#0a0a0f;color:#e8e8f0;font-family:'Space Mono',monospace;padding:24px }}
  h1 {{ font-family:'Syne',sans-serif;font-size:36px;font-weight:800;letter-spacing:-1px }}
  h1 span {{ color:#00e5a0 }}
  table {{ width:100%;border-collapse:collapse;margin-top:16px }}
  th {{ font-size:10px;color:#555;letter-spacing:2px;text-align:left;padding:8px 12px;border-bottom:1px solid #2a2a3a }}
  td {{ padding:10px 12px;border-bottom:1px solid #1a1a24;font-size:13px }}
  tr:hover td {{ background:#111118 }}
  .card {{ background:#111118;border:1px solid #2a2a3a;padding:20px;border-radius:4px }}
  .grid {{ display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin:20px 0 }}
  .tag {{ display:inline-block;font-size:9px;padding:3px 8px;letter-spacing:2px;border-radius:2px }}
  .badge-live {{ background:rgba(0,229,160,.1);border:1px solid rgba(0,229,160,.3);color:#00e5a0;padding:6px 14px;font-size:10px;letter-spacing:2px }}
</style>
</head>
<body>
<div style="max-width:1100px;margin:0 auto">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:28px;flex-wrap:wrap;gap:12px">
    <div>
      <div style="font-size:10px;color:#00e5a0;letter-spacing:4px;margin-bottom:4px">// MERCADO ARGENTINO</div>
      <h1>CEDEAR<span>RADAR</span></h1>
      <div style="font-size:11px;color:#555;margin-top:4px">Powered by InvertirOnline API · Auto-refresh 5min</div>
    </div>
    <div>
      <span class="badge-live">● LIVE</span>
      <div style="font-size:11px;color:#555;margin-top:8px;text-align:right">Actualizado: {ts}</div>
    </div>
  </div>

  <!-- Macro strip -->
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-bottom:28px">
    <div class="card" style="border-top:2px solid #00e5a0">
      <div style="font-size:10px;color:#555;letter-spacing:2px;margin-bottom:6px">DÓLAR CCL</div>
      <div style="font-size:26px;font-weight:700;font-family:'Syne',sans-serif">{ccl}</div>
      <div style="font-size:10px;color:#555;margin-top:4px">estimado</div>
    </div>
    <div class="card" style="border-top:2px solid #7c3aed">
      <div style="font-size:10px;color:#555;letter-spacing:2px;margin-bottom:6px">CEDEARs AL ALZA</div>
      <div style="font-size:26px;font-weight:700;font-family:'Syne',sans-serif;color:#00e5a0">
        {sum(1 for r in analizador.resultados if r['variacion'] >= 0)}
      </div>
    </div>
    <div class="card" style="border-top:2px solid #ef4444">
      <div style="font-size:10px;color:#555;letter-spacing:2px;margin-bottom:6px">CEDEARs A LA BAJA</div>
      <div style="font-size:26px;font-weight:700;font-family:'Syne',sans-serif;color:#ef4444">
        {sum(1 for r in analizador.resultados if r['variacion'] < 0)}
      </div>
    </div>
    <div class="card" style="border-top:2px solid #f59e0b">
      <div style="font-size:10px;color:#555;letter-spacing:2px;margin-bottom:6px">TOTAL ANALIZADOS</div>
      <div style="font-size:26px;font-weight:700;font-family:'Syne',sans-serif">{len(analizador.resultados)}</div>
    </div>
  </div>

  <!-- Sectores -->
  <div style="font-size:11px;color:#00e5a0;letter-spacing:3px;margin-bottom:12px">// SECTORES</div>
  <div class="grid">{sector_cards}</div>

  <!-- Ranking -->
  <div class="card" style="margin-top:8px">
    <div style="font-size:11px;color:#00e5a0;letter-spacing:3px;margin-bottom:4px">// TOP 15 — RENDIMIENTO HOY</div>
    <table>
      <thead>
        <tr>
          <th>#</th><th>TICKER</th><th>VARIACIÓN</th><th>PRECIO ARS</th><th>SECTOR</th><th>VOLUMEN</th>
        </tr>
      </thead>
      <tbody>{rows_top}</tbody>
    </table>
  </div>

  {seccion_proyecciones}

  <div style="font-size:10px;color:#333;margin-top:24px;line-height:1.8">
    ⚠ AVISO LEGAL: Análisis informativo únicamente. No constituye asesoramiento financiero.
    Toda inversión conlleva riesgo. Datos provistos por InvertirOnline API + Yahoo Finance.
  </div>
</div>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    analizador = None

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            html = generar_html(self.analizador).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(html))
            self.end_headers()
            self.wfile.write(html)
        elif self.path == "/api/data":
            data = json.dumps(self.analizador.resultados, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass  # silencia los logs HTTP en consola


def iniciar_dashboard(analizador, port=8080):
    DashboardHandler.analizador = analizador
    server = HTTPServer(("localhost", port), DashboardHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"\n  {verde('✓ Dashboard levantado')} → {cyan(f'http://localhost:{port}')}")
    print(f"  {gris('Se actualiza automáticamente cada 5 minutos')}")
    return server


# ─────────────────────────────────────────────
#  LOOP DE ACTUALIZACIÓN PERIÓDICA
# ─────────────────────────────────────────────
def loop_actualizacion(analizador, intervalo_min=15):
    """Re-analiza el mercado cada N minutos."""
    while True:
        print(f"\n{gris(f'  [auto-refresh] Actualizando en {intervalo_min} min...')}")
        time.sleep(intervalo_min * 60)
        try:
            analizador.analizar_todos()
            analizador.imprimir_ranking()
        except Exception as e:
            print(rojo(f"  Error en actualización: {e}"))


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="CEDEAR Radar Bot — IOL API")
    parser.add_argument("--solo-terminal", action="store_true", help="Solo mostrar en consola, sin dashboard web")
    parser.add_argument("--ticker", type=str, help="Analizar un ticker específico")
    parser.add_argument("--port", type=int, default=DASHBOARD_PORT, help=f"Puerto del dashboard (default: {DASHBOARD_PORT})")
    parser.add_argument("--intervalo", type=int, default=15, help="Minutos entre actualizaciones (default: 15)")
    parser.add_argument("--top", type=int, default=10, help="Cuántos CEDEARs mostrar en el ranking")
    parser.add_argument("--proyecciones", action="store_true", help="Calcular proyecciones corto/largo plazo (tarda ~1 min extra)")
    args = parser.parse_args()

    # Validar credenciales
    if IOL_USER == "TU_EMAIL_IOL" or IOL_PASSWORD == "TU_PASSWORD_IOL":
        print(rojo("\n  ✗ ERROR: Configurá tus credenciales de IOL"))
        print(amarillo("  Opción 1 — Variables de entorno:"))
        print(gris("    export IOL_USER='tu@email.com'"))
        print(gris("    export IOL_PASSWORD='tu_password'\n"))
        print(amarillo("  Opción 2 — Editá directamente el archivo:"))
        print(gris("    IOL_USER     = 'tu@email.com'"))
        print(gris("    IOL_PASSWORD = 'tu_password'"))
        print()
        sys.exit(1)

    # Inicializar cliente
    try:
        iol       = IOLClient(IOL_USER, IOL_PASSWORD)
        iol.login()
        analizador = AnalizadorCEDEARs(iol)
    except Exception as e:
        print(rojo(f"\n  ✗ No se pudo conectar a IOL: {e}"))
        print(amarillo("  Verificá usuario/contraseña y conexión a internet."))
        sys.exit(1)

    # Análisis puntual de un ticker
    if args.ticker:
        analizador.estimar_ccl()
        analizador.analizar_ticker(args.ticker)
        return

    # Análisis completo
    analizador.analizar_todos()
    analizador.imprimir_ranking(top_n=args.top)
    analizador.oportunidades()

    # Proyecciones corto/largo plazo
    if args.proyecciones:
        analizador.proyecciones(top_n=args.top)

    # Dashboard web
    if not args.solo_terminal:
        servidor = iniciar_dashboard(analizador, port=args.port)
        print(f"\n  {amarillo('Presioná Ctrl+C para detener')}")

        # Loop de actualización en background
        update_thread = Thread(
            target=loop_actualizacion,
            args=(analizador, args.intervalo),
            daemon=True
        )
        update_thread.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n\n  {gris('Detenido. ¡Hasta la próxima!')}\n")
            servidor.shutdown()
    else:
        print(f"\n  {gris('Modo solo-terminal. Fin del análisis.')}\n")


if __name__ == "__main__":
    main()
