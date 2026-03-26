/* ============================================================
   CEDEAR RADAR — JavaScript para index.html
   ============================================================
   INSTRUCCIONES DE USO:
   1. Pegá este bloque completo antes del </body> de tu index.html
   2. Agregá los elementos HTML marcados con "PEGAR EN HTML" donde
      quieras que aparezcan en tu página
   3. Arranca el servidor: python server.py
   4. Abrí index.html en el navegador
   ============================================================ */


/* ============================================================
   PEGAR EN HTML — Botón "TOP CEDEARs HOY"
   Pegá esto donde quieras el botón en tu página:

   <button onclick="CedearRadar.analizar()" id="btn-analizar">
     📊 TOP CEDEARs HOY
   </button>

   <button onclick="CedearRadar.analizar(true)" id="btn-proyecciones">
     🔮 + Proyecciones (tarda ~1 min)
   </button>

   <!-- Contenedor donde aparecen los resultados -->
   <div id="cedear-resultado"></div>
   ============================================================ */


const CedearRadar = (() => {

  const API = "http://localhost:5000/api";
  let _polling = null;

  // ── Helpers UI ────────────────────────────────────────────
  function el(id) { return document.getElementById(id); }

  function setBtn(texto, desactivado = false) {
    const btn = el("btn-analizar");
    if (btn) { btn.textContent = texto; btn.disabled = desactivado; }
    const btn2 = el("btn-proyecciones");
    if (btn2) btn2.disabled = desactivado;
  }

  function render(html) {
    const contenedor = el("cedear-resultado");
    if (contenedor) contenedor.innerHTML = html;
  }

  function colorVar(v) {
    if (v > 0)  return `<span style="color:#00e5a0;font-weight:700">▲ +${v.toFixed(2)}%</span>`;
    if (v < 0)  return `<span style="color:#ef4444;font-weight:700">▼ ${v.toFixed(2)}%</span>`;
    return `<span style="color:#999">— 0.00%</span>`;
  }

  function colorScore(s) {
    const c = s >= 65 ? "#00e5a0" : s >= 45 ? "#f59e0b" : "#ef4444";
    const pct = s;
    return `<span style="color:${c};font-weight:700">${s}/100</span>
            <span style="display:inline-block;width:60px;height:6px;background:#222;border-radius:3px;margin-left:6px;vertical-align:middle">
              <span style="display:block;width:${pct}%;height:6px;background:${c};border-radius:3px"></span>
            </span>`;
  }

  // ── Spinner de carga ──────────────────────────────────────
  function mostrarCargando(msg = "Analizando CEDEARs...") {
    render(`
      <div style="text-align:center;padding:60px 20px;font-family:monospace">
        <div style="font-size:32px;margin-bottom:16px;animation:spin 1.5s linear infinite;display:inline-block">⟳</div>
        <div style="color:#00e5a0;letter-spacing:2px;font-size:13px">${msg}</div>
        <div style="color:#444;font-size:11px;margin-top:8px">Conectado a IOL · puede tardar 30-60 segundos</div>
      </div>
      <style>@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}</style>
    `);
  }

  // ── Render principal de resultados ────────────────────────
  function renderResultados(data) {
    const ts  = data.timestamp ? new Date(data.timestamp).toLocaleString("es-AR") : "—";
    const ccl = data.ccl ? `$${Math.round(data.ccl).toLocaleString("es-AR")}` : "N/D";
    const cedears = data.cedears || [];
    const proy    = data.proyecciones || [];

    // ── Macro strip ──
    const alza  = cedears.filter(r => r.variacion >= 0).length;
    const baja  = cedears.filter(r => r.variacion < 0).length;

    let html = `
      <div style="font-family:monospace;max-width:1000px">

        <!-- Macro -->
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:24px">
          ${macroCard("DÓLAR CCL", ccl, "#00e5a0")}
          ${macroCard("AL ALZA", alza, "#00e5a0")}
          ${macroCard("A LA BAJA", baja, "#ef4444")}
          ${macroCard("ANALIZADOS", cedears.length, "#7c3aed")}
        </div>

        <!-- TOP 15 -->
        <div style="background:#111118;border:1px solid #2a2a3a;padding:20px;margin-bottom:16px">
          <div style="color:#00e5a0;font-size:11px;letter-spacing:3px;margin-bottom:14px">
            🏆 TOP 15 — RENDIMIENTO HOY · ${ts}
          </div>
          <table style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>
              <tr style="color:#555;font-size:10px;letter-spacing:1px;border-bottom:1px solid #2a2a3a">
                <th style="padding:6px 8px;text-align:left">#</th>
                <th style="padding:6px 8px;text-align:left">TICKER</th>
                <th style="padding:6px 8px;text-align:right">VARIACIÓN</th>
                <th style="padding:6px 8px;text-align:right">PRECIO ARS</th>
                <th style="padding:6px 8px;text-align:left">SECTOR</th>
                <th style="padding:6px 8px;text-align:right">VOLUMEN</th>
              </tr>
            </thead>
            <tbody>
              ${cedears.slice(0, 15).map((r, i) => `
                <tr style="border-bottom:1px solid #1a1a24;cursor:pointer"
                    onmouseover="this.style.background='#1a1a24'"
                    onmouseout="this.style.background=''"
                    onclick="CedearRadar.detalle('${r.ticker}')">
                  <td style="padding:10px 8px;color:#555">${i + 1}</td>
                  <td style="padding:10px 8px"><strong style="font-size:15px">${r.ticker}</strong></td>
                  <td style="padding:10px 8px;text-align:right">${colorVar(r.variacion)}</td>
                  <td style="padding:10px 8px;text-align:right">$${r.precio.toLocaleString("es-AR", {minimumFractionDigits:2})}</td>
                  <td style="padding:10px 8px;color:#555;font-size:11px">${r.sector}</td>
                  <td style="padding:10px 8px;text-align:right;color:#555">${r.volumen.toLocaleString("es-AR")}</td>
                </tr>`).join("")}
            </tbody>
          </table>
          <div style="color:#333;font-size:10px;margin-top:10px">
            💡 Hacé click en un ticker para ver el análisis detallado
          </div>
        </div>`;

    // ── Proyecciones (si existen) ──
    if (proy.length > 0) {
      const top_cp = [...proy].sort((a, b) => b.score_corto - a.score_corto).slice(0, 8);
      const top_lp = [...proy].sort((a, b) => b.score_largo - a.score_largo).slice(0, 8);
      const combinados = [...proy]
        .sort((a, b) => (b.score_corto + b.score_largo) - (a.score_corto + a.score_largo))
        .slice(0, 6);

      html += `
        <!-- Proyecciones -->
        <div style="background:#111118;border:1px solid #2a2a3a;padding:20px;margin-bottom:16px">
          <div style="color:#7c3aed;font-size:11px;letter-spacing:3px;margin-bottom:16px">🔮 PROYECCIONES TÉCNICAS</div>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
            <div>
              <div style="color:#00e5a0;font-size:10px;letter-spacing:2px;margin-bottom:10px">
                📅 CORTO PLAZO (días/semanas)
              </div>
              ${tablaProyecciones(top_cp, "score_corto", "label_corto")}
            </div>
            <div>
              <div style="color:#a78bfa;font-size:10px;letter-spacing:2px;margin-bottom:10px">
                📆 LARGO PLAZO (meses)
              </div>
              ${tablaProyecciones(top_lp, "score_largo", "label_largo")}
            </div>
          </div>

          <div style="color:#f59e0b;font-size:10px;letter-spacing:2px;margin-bottom:10px">
            🎯 MATRIZ COMBINADA
          </div>
          <table style="width:100%;border-collapse:collapse;font-size:12px">
            <thead>
              <tr style="color:#555;font-size:10px;border-bottom:1px solid #2a2a3a">
                <th style="padding:6px 8px;text-align:left">TICKER</th>
                <th style="padding:6px 8px">CORTO</th>
                <th style="padding:6px 8px">LARGO</th>
                <th style="padding:6px 8px">TOTAL</th>
                <th style="padding:6px 8px;text-align:left">VEREDICTO</th>
              </tr>
            </thead>
            <tbody>
              ${combinados.map(ind => {
                const comb = ind.score_corto + ind.score_largo;
                const c = comb >= 140 ? "#00e5a0" : comb >= 110 ? "#f59e0b" : "#ef4444";
                const v = comb >= 140 ? "⭐ MUY RECOMENDADO" : comb >= 110 ? "✓ RECOMENDADO" : comb >= 80 ? "~ NEUTRAL" : "✗ PRECAUCIÓN";
                return `<tr style="border-bottom:1px solid #1a1a24">
                  <td style="padding:8px"><strong>${ind.ticker}</strong></td>
                  <td style="padding:8px;text-align:center">${colorScore(ind.score_corto)}</td>
                  <td style="padding:8px;text-align:center">${colorScore(ind.score_largo)}</td>
                  <td style="padding:8px;text-align:center;color:${c};font-weight:700">${comb}/200</td>
                  <td style="padding:8px;color:${c}">${v}</td>
                </tr>`;
              }).join("")}
            </tbody>
          </table>
        </div>`;
    }

    // ── Detalle ticker (placeholder) ──
    html += `<div id="cedear-detalle"></div>`;

    // ── Disclaimer ──
    html += `
        <div style="color:#333;font-size:10px;line-height:1.8;border-top:1px solid #1a1a24;padding-top:12px">
          ⚠ AVISO LEGAL: Análisis informativo únicamente. No constituye asesoramiento financiero profesional.
          Toda inversión conlleva riesgo de pérdida de capital. Datos: IOL + Yahoo Finance.
        </div>
      </div>`;

    render(html);
  }

  function macroCard(titulo, valor, color) {
    return `
      <div style="background:#111118;border:1px solid #2a2a3a;border-top:2px solid ${color};padding:14px">
        <div style="font-size:10px;color:#555;letter-spacing:2px;margin-bottom:6px">${titulo}</div>
        <div style="font-size:22px;font-weight:700;color:${color}">${valor}</div>
      </div>`;
  }

  function tablaProyecciones(lista, campoScore, campoLabel) {
    return `
      <table style="width:100%;border-collapse:collapse;font-size:12px">
        <thead>
          <tr style="color:#555;font-size:10px;border-bottom:1px solid #2a2a3a">
            <th style="padding:5px 6px;text-align:left">TICKER</th>
            <th style="padding:5px 6px">SCORE</th>
            <th style="padding:5px 6px;text-align:left">SEÑAL</th>
          </tr>
        </thead>
        <tbody>
          ${lista.map((ind, i) => {
            const sc = ind[campoScore];
            const lb = ind[campoLabel] || "";
            const c  = sc >= 65 ? "#00e5a0" : sc >= 45 ? "#f59e0b" : "#ef4444";
            return `<tr style="border-bottom:1px solid #1a1a24">
              <td style="padding:7px 6px"><strong>${ind.ticker}</strong></td>
              <td style="padding:7px 6px;text-align:center;color:${c};font-weight:700">${sc}</td>
              <td style="padding:7px 6px;color:${c};font-size:11px">${lb}</td>
            </tr>`;
          }).join("")}
        </tbody>
      </table>`;
  }

  // ── Detalle de un ticker ──────────────────────────────────
  async function detalle(ticker) {
    const cont = el("cedear-detalle");
    if (!cont) return;
    cont.innerHTML = `<div style="padding:20px;color:#555;font-family:monospace;font-size:12px">Cargando ${ticker}...</div>`;
    cont.scrollIntoView({ behavior: "smooth" });

    try {
      const res  = await fetch(`${API}/ticker/${ticker}`);
      const data = await res.json();
      if (!data.ok) {
        cont.innerHTML = `<div style="color:#ef4444;padding:16px;font-family:monospace">✗ ${data.mensaje}</div>`;
        return;
      }

      const ind   = data.indicadores || {};
      const ratio = data.ratio_ccl;
      const ratioColor = ratio < 0.95 ? "#00e5a0" : ratio > 1.05 ? "#ef4444" : "#f59e0b";
      const ratioLabel = ratio < 0.95 ? "DESCUENTO ✓" : ratio > 1.05 ? "PRIMA ✗" : "PRECIO JUSTO";

      cont.innerHTML = `
        <div style="background:#0d0d15;border:1px solid #7c3aed;border-top:2px solid #7c3aed;padding:20px;margin-top:16px;font-family:monospace">
          <div style="display:flex;justify-content:space-between;align-items:start;flex-wrap:wrap;gap:12px;margin-bottom:16px">
            <div>
              <div style="font-size:28px;font-weight:800;letter-spacing:-1px">${ticker}</div>
              <div style="color:#555;font-size:11px">Análisis detallado</div>
            </div>
            <button onclick="el('cedear-detalle').innerHTML=''"
                    style="background:transparent;border:1px solid #333;color:#555;padding:6px 12px;cursor:pointer;font-family:monospace;font-size:11px">
              ✕ cerrar
            </button>
          </div>

          <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin-bottom:16px">
            ${detalleCard("PRECIO ARS",   `$${data.precio.toLocaleString("es-AR",{minimumFractionDigits:2})}`, "#e8e8f0")}
            ${detalleCard("VARIACIÓN",     colorVar(data.variacion), "#e8e8f0")}
            ${detalleCard("MÁXIMO",       `$${data.maximo.toLocaleString("es-AR",{minimumFractionDigits:2})}`, "#e8e8f0")}
            ${detalleCard("MÍNIMO",       `$${data.minimo.toLocaleString("es-AR",{minimumFractionDigits:2})}`, "#e8e8f0")}
            ${detalleCard("VOLUMEN",       data.volumen.toLocaleString("es-AR"), "#e8e8f0")}
            ${ratio ? detalleCard("RATIO CCL", `<span style="color:${ratioColor}">${ratio.toFixed(3)}x — ${ratioLabel}</span>`, ratioColor) : ""}
          </div>

          ${ind.sma20 ? `
          <div style="border-top:1px solid #1a1a24;padding-top:14px;margin-top:4px">
            <div style="color:#555;font-size:10px;letter-spacing:2px;margin-bottom:10px">INDICADORES TÉCNICOS</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;font-size:12px">
              ${ind.sma20  ? detalleCard("SMA 20",  `$${ind.sma20.toLocaleString("es-AR",{minimumFractionDigits:2})}`, "#7c7c9a") : ""}
              ${ind.sma50  ? detalleCard("SMA 50",  `$${ind.sma50.toLocaleString("es-AR",{minimumFractionDigits:2})}`, "#7c7c9a") : ""}
              ${ind.sma200 ? detalleCard("SMA 200", `$${ind.sma200.toLocaleString("es-AR",{minimumFractionDigits:2})}`, "#7c7c9a") : ""}
              ${ind.rsi14  ? detalleCard("RSI 14", ind.rsi14.toFixed(1),
                  ind.rsi14 < 35 ? "#00e5a0" : ind.rsi14 > 70 ? "#ef4444" : "#f59e0b") : ""}
              ${ind.bb_upper ? detalleCard("BB Superior", `$${ind.bb_upper.toLocaleString("es-AR",{minimumFractionDigits:2})}`, "#7c7c9a") : ""}
              ${ind.bb_lower ? detalleCard("BB Inferior", `$${ind.bb_lower.toLocaleString("es-AR",{minimumFractionDigits:2})}`, "#7c7c9a") : ""}
            </div>
            ${ind.score_corto !== undefined ? `
            <div style="margin-top:14px;display:grid;grid-template-columns:1fr 1fr;gap:10px">
              <div style="background:#111118;border:1px solid #2a2a3a;padding:12px">
                <div style="color:#555;font-size:10px;margin-bottom:6px">CORTO PLAZO</div>
                <div>${colorScore(ind.score_corto)}</div>
                <div style="color:#666;font-size:11px;margin-top:4px">${ind.label_corto || ""}</div>
              </div>
              <div style="background:#111118;border:1px solid #2a2a3a;padding:12px">
                <div style="color:#555;font-size:10px;margin-bottom:6px">LARGO PLAZO</div>
                <div>${colorScore(ind.score_largo)}</div>
                <div style="color:#666;font-size:11px;margin-top:4px">${ind.label_largo || ""}</div>
              </div>
            </div>` : ""}
          </div>` : ""}
        </div>`;
    } catch (e) {
      cont.innerHTML = `<div style="color:#ef4444;padding:16px;font-family:monospace">✗ Error: ${e.message}</div>`;
    }
  }

  function detalleCard(titulo, valor, color = "#e8e8f0") {
    return `
      <div style="background:#111118;border:1px solid #1a1a24;padding:10px">
        <div style="font-size:9px;color:#444;letter-spacing:1px;margin-bottom:4px">${titulo}</div>
        <div style="font-size:13px;color:${color}">${valor}</div>
      </div>`;
  }

  // ── Polling — espera hasta que el análisis termine ────────
  function iniciarPolling(callback) {
    if (_polling) clearInterval(_polling);
    _polling = setInterval(async () => {
      try {
        const res  = await fetch(`${API}/resultado`);
        const data = await res.json();
        if (!data.analizando) {
          clearInterval(_polling);
          _polling = null;
          if (data.error) {
            render(`<div style="color:#ef4444;padding:20px;font-family:monospace">✗ Error: ${data.error}</div>`);
            setBtn("📊 TOP CEDEARs HOY");
          } else {
            callback(data);
            setBtn("📊 TOP CEDEARs HOY");
          }
        }
      } catch (e) {
        clearInterval(_polling);
        render(`<div style="color:#ef4444;padding:20px;font-family:monospace">
          ✗ No se pudo conectar al servidor.<br>
          <small>¿Está corriendo <code>python server.py</code>?</small>
        </div>`);
        setBtn("📊 TOP CEDEARs HOY");
      }
    }, 2000); // chequea cada 2 segundos
  }

  // ── Función principal — llamada por el botón ──────────────
  async function analizar(conProyecciones = false) {
    setBtn("⟳ Analizando...", true);
    mostrarCargando(conProyecciones ? "Analizando + calculando proyecciones..." : "Analizando CEDEARs...");

    try {
      // Verificar que el servidor esté levantado
      const statusRes = await fetch(`${API}/status`).catch(() => null);
      if (!statusRes || !statusRes.ok) {
        render(`<div style="color:#ef4444;padding:24px;font-family:monospace;line-height:2">
          ✗ No se encontró el servidor en localhost:5000<br>
          <strong>Para activarlo:</strong><br>
          1. Abrí una terminal<br>
          2. Navegá a la carpeta del proyecto<br>
          3. Ejecutá: <code style="background:#1a1a24;padding:2px 6px">python server.py</code>
        </div>`);
        setBtn("📊 TOP CEDEARs HOY");
        return;
      }

      // Disparar el análisis
      await fetch(`${API}/analizar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proyecciones: conProyecciones }),
      });

      // Esperar resultado vía polling
      iniciarPolling(renderResultados);

    } catch (e) {
      render(`<div style="color:#ef4444;padding:20px;font-family:monospace">✗ ${e.message}</div>`);
      setBtn("📊 TOP CEDEARs HOY");
    }
  }

  // ── API pública ───────────────────────────────────────────
  return { analizar, detalle };

})();
