/* ============================================================
   Gestor de Tareas - lógica del frontend (estilo Google Calendar)
   ============================================================ */

"use strict";

// ---------------------- Estado global ----------------------
const HORA_PX = 48;                       // altura en px de 1 hora
const DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"];
const DIAS_LARGO = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
               "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const PRIO_NOMBRE = { 1: "Máxima", 2: "Alta", 3: "Media", 4: "Baja", 5: "Mínima" };

let inicioVisible = lunesDe(new Date());  // primer día visible (inicio de la vista)
let finVisible = new Date(inicioVisible); // último día visible (fin de la vista)
finVisible.setDate(inicioVisible.getDate() + 6);
let mesMini = new Date();                 // mes del mini calendario
let tareas = [];                          // todas las tareas
let bloquesPorTarea = new Map();          // tarea_id -> bloques asignados ordenados por inicio
let tareaEditandoId = null;               // null = crear
let bloqueArrastrado = null;              // bloque en curso de drag and drop
let anilloArrastrado = null;              // "inicio" | "fin" durante el arrastre de anillos

// ---------------------- Iconos SVG (sin emojis) ----------------------
const SVG_ATTR = "fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"";
const ICONO_CANDADO = `<svg class="ic" width="12" height="12" viewBox="0 0 24 24" ${SVG_ATTR}><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>`;
const ICONO_RECURRENCIA = `<svg class="ic" width="12" height="12" viewBox="0 0 24 24" ${SVG_ATTR}><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>`;
const ICONO_RELOJ = `<svg class="ic" width="12" height="12" viewBox="0 0 24 24" ${SVG_ATTR}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`;
const ICONO_PIN = `<svg class="ic" width="11" height="11" viewBox="0 0 24 24" ${SVG_ATTR}><path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1z"/></svg>`;
const ICONO_CHECK = `<svg width="14" height="14" viewBox="0 0 24 24" ${SVG_ATTR}><polyline points="20 6 9 17 4 12"/></svg>`;
const ICONO_LAPIZ = `<svg width="14" height="14" viewBox="0 0 24 24" ${SVG_ATTR}><path d="M17 3a2.83 2.83 0 0 1 4 4L7.5 20.5 2 22l1.5-5.5z"/></svg>`;
const ICONO_PAPELERA = `<svg width="14" height="14" viewBox="0 0 24 24" ${SVG_ATTR}><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;
const ICONO_MOVER = `<svg width="13" height="13" viewBox="0 0 24 24" ${SVG_ATTR}><polyline points="5 9 2 12 5 15"/><polyline points="9 5 12 2 15 5"/><polyline points="15 19 12 22 9 19"/><polyline points="19 9 22 12 19 15"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/></svg>`;

// ---------------------- Utilidades de fecha ----------------------
function pad(n) { return String(n).padStart(2, "0"); }

function fmt(d) {
  // -> "YYYY-MM-DD HH:MM:SS" local (formato de la API)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
         `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function fromFmt(s) {
  if (!s) return null;
  const [fecha, hora] = s.split(" ");
  const [y, m, d] = fecha.split("-").map(Number);
  const [hh, mm, ss] = hora.split(":").map(Number);
  return new Date(y, m - 1, d, hh, mm, ss || 0);
}

function fmtVentana(ini, fin) {
  // "2026-08-11 11:30:00" -> "11/08 11:30 al 18/08 10:00"
  const a = fromFmt(ini), b = fromFmt(fin);
  if (!a || !b) return "";
  const f = (d) =>
    `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return `${f(a)} al ${f(b)}`;
}

function toLocalInput(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalInput(s) {
  if (!s) return null;
  const [fecha, hora] = s.split("T");
  const [y, m, d] = fecha.split("-").map(Number);
  const [hh, mm] = hora.split(":").map(Number);
  return new Date(y, m - 1, d, hh, mm);
}

function lunesDe(d) {
  const r = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dia = (r.getDay() + 6) % 7;      // lunes = 0
  r.setDate(r.getDate() - dia);
  return r;
}

/** Diferencia de días entre dos fechas ignorando la hora. */
function diffDias(a, b) {
  const d1 = new Date(a.getFullYear(), a.getMonth(), a.getDate());
  const d2 = new Date(b.getFullYear(), b.getMonth(), b.getDate());
  return Math.round((d2 - d1) / 86400000);
}

function minutosDelDia(d) { return d.getHours() * 60 + d.getMinutes(); }
function mismaFecha(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}
function fmtHora(d) {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fmtRango(inicio, fin) {
  return `${fmtHora(inicio)} – ${fmtHora(fin)}`;
}

/** Rango visible de un segmento: la medianoche se muestra como 24:00. */
function fmtSegRango(inicio, fin) {
  const f = d => (d.getHours() === 0 && d.getMinutes() === 0) ? "24:00" : fmtHora(d);
  return `${fmtHora(inicio)} – ${f(fin)}`;
}

/** Etiqueta del rango visible en la barra superior. */
function tituloRango() {
  const a = inicioVisible;
  const b = finVisible;
  const numDias = diffDias(a, b) + 1;
  const mismoMes = a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth();
  if (numDias === 7 && mismoMes) return `${MESES[a.getMonth()]} ${a.getFullYear()}`;
  const anioActual = new Date().getFullYear();
  const f = d => {
    const base = `${DIAS[(d.getDay() + 6) % 7]} ${d.getDate()} ${MESES[d.getMonth()]}`;
    return d.getFullYear() === anioActual ? base : `${base} ${d.getFullYear()}`;
  };
  return `${f(a)} – ${f(b)}`;
}

/** True si el dispositivo es táctil (no hay drag and drop nativo). */
function esTactil() {
  return window.matchMedia("(pointer: coarse)").matches
    || "ontouchstart" in window
    || (navigator.maxTouchPoints || 0) > 0;
}

/** Mueve un extremo de la vista (anillo verde o rojo) a otra fecha. */
function moverExtremo(tipo, fecha) {
  const destino = new Date(fecha.getFullYear(), fecha.getMonth(), fecha.getDate());
  if (tipo === "inicio") {
    if (destino >= finVisible) {
      toast("El inicio de la vista debe ser anterior al fin", true);
      return;
    }
    if (diffDias(destino, finVisible) + 1 > 28) {
      toast("El rango visible máximo es de 28 días", true);
      return;
    }
    inicioVisible = destino;
  } else {
    if (destino <= inicioVisible) {
      toast("El fin de la vista debe ser posterior al inicio", true);
      return;
    }
    if (diffDias(inicioVisible, destino) + 1 > 28) {
      toast("El rango visible máximo es de 28 días", true);
      return;
    }
    finVisible = destino;
  }
  cargarTodo();
  guardarPreferencias();
}

// ---------------------- API ----------------------
async function api(ruta, opciones = {}) {
  const r = await fetch(ruta, {
    credentials: "same-origin",
    cache: "no-store",   // evitar respuestas cacheadas al navegar entre semanas
    headers: opciones.body ? { "Content-Type": "application/json" } : undefined,
    ...opciones,
  });
  if (r.status === 401) { location.href = "/"; throw new Error("no-autenticado"); }
  if (r.status === 204) return null;
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new Error(data && data.detail ? data.detail : `Error ${r.status}`);
  return data;
}

// ---------------------- Preferencias ----------------------
/** Fecha ISO yyyy-mm-dd para persistir preferencias. */
function fmtDiaISO(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Parsea una fecha ISO yyyy-mm-dd a medianoche local (o null). */
function parseDiaISO(s) {
  if (!s) return null;
  const partes = s.split("-").map(Number);
  if (partes.length !== 3 || partes.some(n => !Number.isFinite(n))) return null;
  return new Date(partes[0], partes[1] - 1, partes[2]);
}

/** Guarda el tema y la posición de la vista en el servidor (sin bloquear). */
function guardarPreferencias() {
  api("/api/preferencias", {
    method: "PUT",
    body: JSON.stringify({
      tema: document.documentElement.dataset.theme || "claro",
      inicio_visible: fmtDiaISO(inicioVisible),
      fin_visible: fmtDiaISO(finVisible)
    })
  }).catch(() => null);
}

// ---------------------- Carga de datos ----------------------
async function cargarTodo() {
  const fin = new Date(finVisible);
  fin.setDate(fin.getDate() + 1);
  const [t, b, todos, np] = await Promise.all([
    api("/api/tareas"),
    api(`/api/horario/bloques?inicio=${encodeURIComponent(fmt(inicioVisible))}&fin=${encodeURIComponent(fmt(fin))}`),
    api("/api/horario/bloques"),
    api("/api/tareas/no-programadas").catch(() => []),
  ]);
  tareas = t;
  // Bloques asignados de TODAS las tareas (no solo del rango visible):
  // "Mis tareas" se clasifica por la hora realmente asignada a cada tarea,
  // no por la ventana de asignación de la tarea.
  const mapa = new Map();
  for (const bl of todos || []) {
    const ini = fromFmt(bl.inicio);
    const finBl = fromFmt(bl.fin);
    if (!ini || !finBl) continue;
    if (!mapa.has(bl.tarea_id)) mapa.set(bl.tarea_id, []);
    mapa.get(bl.tarea_id).push({ inicio: ini.getTime(), fin: finBl.getTime() });
  }
  for (const lista of mapa.values()) lista.sort((a, b) => a.inicio - b.inicio);
  bloquesPorTarea = mapa;
  renderCalendario(b);
  renderMiniCal();
  renderListaTareas();
  renderNoProgramadas(np);
}

// ---------------------- Calendario semanal ----------------------
function renderCalendario(bloques) {
  const cal = document.getElementById("cal");
  cal.innerHTML = "";

  const numDias = diffDias(inicioVisible, finVisible) + 1;
  // En pantallas estrechas la columna de horas se angosta para dar más
  // espacio a los días, sin romper la legibilidad de las horas.
  const movil = window.innerWidth <= 480;
  const anchoHora = movil ? 48 : 64;
  const anchoDia = movil ? 86 : 92;
  cal.style.gridTemplateColumns = `${anchoHora}px repeat(${numDias}, minmax(${anchoDia}px, 1fr))`;

  // Título de la barra superior
  document.getElementById("tb-title").textContent = tituloRango();

  const hoy = new Date();

  // Esquina superior izquierda
  const corner = document.createElement("div");
  corner.className = "corner";
  cal.appendChild(corner);

  // Cabeceras de días: anillos de inicio (verde), hoy (relleno) y fin (rojo)
  for (let i = 0; i < numDias; i++) {
    const dia = new Date(inicioVisible);
    dia.setDate(inicioVisible.getDate() + i);
    let cls = "day-head";
    const esInicio = mismaFecha(dia, inicioVisible);
    const esFin = mismaFecha(dia, finVisible);
    if (esInicio) cls += " ring-start";
    if (esFin) cls += " ring-end";
    if (mismaFecha(dia, hoy)) cls += " hoy";
    const head = document.createElement("div");
    head.className = cls;
    const titulos = [];
    if (esInicio) titulos.push("Inicio de la vista: arrástralo a otro día para moverlo");
    if (esFin) titulos.push("Fin de la vista: arrástralo a otro día para moverlo");
    if (mismaFecha(dia, hoy)) titulos.push("Hoy");
    head.title = titulos.join(" · ");
    head.innerHTML = `
      <div class="d-name">${DIAS[(dia.getDay() + 6) % 7]}</div>
      <div class="d-num">${dia.getDate()}</div>`;

    // Los anillos de inicio y fin se arrastran para redefinir el rango visible
    if (esInicio || esFin) {
      head.draggable = true;
      head.dataset.anillo = esInicio ? "inicio" : "fin";
      head.addEventListener("dragstart", (ev) => {
        anilloArrastrado = head.dataset.anillo;
        ev.dataTransfer.setData("text/plain", head.dataset.anillo);
        ev.dataTransfer.effectAllowed = "move";
        head.classList.add("anillo-dragging");
      });
      head.addEventListener("dragend", () => {
        head.classList.remove("anillo-dragging");
        anilloArrastrado = null;
        document.querySelectorAll(".anillo-drop").forEach(el => el.classList.remove("anillo-drop"));
      });

      // En pantallas táctiles no hay drag and drop: un toque abre el
      // selector de fecha para mover el anillo (misma acción, otro gesto).
      if (esTactil()) {
        head.addEventListener("click", () => abrirMover({
          titulo: esInicio ? "Mover inicio de la vista" : "Mover fin de la vista",
          meta: `Elige la nueva fecha del ${esInicio ? "inicio" : "fin"}.`,
          valorInicial: dia,
          aplicar: (fecha) => moverExtremo(esInicio ? "inicio" : "fin", fecha),
        }));
      }
    }

    // Zona de soltado de anillos sobre las cabeceras
    head.addEventListener("dragover", (ev) => {
      if (!anilloArrastrado) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "move";
      head.classList.add("anillo-drop");
    });
    head.addEventListener("dragleave", () => head.classList.remove("anillo-drop"));
    head.addEventListener("drop", (ev) => {
      ev.preventDefault();
      head.classList.remove("anillo-drop");
      if (!anilloArrastrado) return;
      moverExtremo(anilloArrastrado, dia);
    });

    cal.appendChild(head);
  }

  // Columna de horas
  const hourCol = document.createElement("div");
  hourCol.className = "hour-col";
  hourCol.style.height = `${24 * HORA_PX}px`;
  for (let h = 0; h < 24; h++) {
    const lab = document.createElement("div");
    lab.className = "hour-label";
    lab.style.top = `${h * HORA_PX}px`;
    lab.textContent = h === 0 ? "" : `${h}:00`;
    hourCol.appendChild(lab);
  }
  cal.appendChild(hourCol);

  // Preparar eventos por día: los bloques que cruzan medianoche se dividen
  // en segmentos por día (ej. dormir 23:00-05:00 queda 23:00-24:00 hoy y
  // 0:00-05:00 mañana, cortados en la línea de medianoche).
  const porDia = Array.from({ length: numDias }, () => []);
  const baseVista = new Date(inicioVisible);
  baseVista.setHours(0, 0, 0, 0);
  for (const b of bloques) {
    const ini = fromFmt(b.inicio);
    const finb = fromFmt(b.fin);
    if (!ini || !finb) continue;
    for (let d = diffDias(inicioVisible, ini); ; d++) {
      const diaIni = new Date(baseVista);
      diaIni.setDate(baseVista.getDate() + d);
      const diaFin = new Date(diaIni);
      diaFin.setDate(diaIni.getDate() + 1);
      if (d >= numDias || diaIni >= finb) break;
      const segIni = ini > diaIni ? ini : diaIni;
      const segFin = finb < diaFin ? finb : diaFin;
      if (d >= 0) {
        porDia[d].push({ ...b, start: segIni, end: segFin, col: 0, nCarriles: 1 });
      }
      if (finb <= diaFin) break;
    }
  }

  // Columnas de días
  for (let i = 0; i < numDias; i++) {
    const dia = new Date(inicioVisible);
    dia.setDate(inicioVisible.getDate() + i);

    const col = document.createElement("div");
    col.className = "day-col";
    col.dataset.dia = i;

    for (let h = 0; h <= 24; h++) {
      const line = document.createElement("div");
      line.className = "hour-line" + (h % 24 === 0 || h === 24 ? " major" : "");
      line.style.top = `${h * HORA_PX}px`;
      col.appendChild(line);
    }

    // Línea de "ahora" si es hoy
    if (mismaFecha(dia, hoy)) {
      const nowLine = document.createElement("div");
      nowLine.className = "now-line";
      nowLine.style.top = `${(minutosDelDia(hoy) / 60) * HORA_PX}px`;
      col.appendChild(nowLine);
    }

    // Eventos con reparto de carriles por solape
    const eventos = porDia[i].sort((a, b) => a.start - b.start);
    layoutEventos(eventos);
    for (const e of eventos) {
      const top = (minutosDelDia(e.start) / 60) * HORA_PX;
      const durPx = Math.max(((e.end - e.start) / 3600000) * HORA_PX, 20);
      const el = document.createElement("div");
      const corto = (e.end - e.start) / 60000 <= 45;
      el.title = e.titulo;
      el.className = `event prio-${e.prioridad || 3}` +
        (e.completado ? " done" : "") +
        (corto ? " compact" : "") +
        (e.fijado && !e.es_recurrente ? " fijado" : "");
      el.style.top = `${top + 2}px`;
      el.style.height = `${durPx - 4}px`;
      el.style.left = `calc(${(e.col * 100) / e.nCarriles}% + 3px)`;
      el.style.width = `calc(${100 / e.nCarriles}% - 6px)`;
      el.innerHTML = corto
        ? `<span class="e-time">${fmtHora(e.start)}</span><span class="e-title">${escapeHtml(e.titulo)}</span>`
        : `<div class="e-title">${escapeHtml(e.titulo)}</div><div class="e-time">${fmtSegRango(e.start, e.end)}</div>`;
      if (e.es_recurrente) {
        const ventana = e.ventana_inicio
          ? ` (${fmtVentana(e.ventana_inicio, e.ventana_fin)})` : "";
        el.innerHTML += `<span class="e-lock" title="Bloque recurrente: solo se mueve dentro de su ventana${ventana}">${ICONO_RECURRENCIA}</span>`;
        el.title = `${e.titulo} · Bloque recurrente: se mueve solo dentro de su ventana${ventana}`;
      } else if (e.fijado) {
        el.innerHTML += `<span class="e-pin" title="Movido a mano: se conserva al regenerar el horario">${ICONO_PIN}</span>`;
        el.title = e.titulo;
      }
      el.addEventListener("click", (ev) => abrirPopover(ev, e));

      // Drag and drop para mover (todos los bloques, salvo completados)
      if (!e.completado) {
        el.draggable = true;
        el.title = e.es_recurrente
          ? `${e.titulo} · Arrastra para mover (solo dentro de su ventana)`
          : `${e.titulo} · Arrastra para mover`;
        el.addEventListener("dragstart", (ev) => {
          bloqueArrastrado = e;
          ev.dataTransfer.setData("text/plain", String(e.id));
          ev.dataTransfer.effectAllowed = "move";
          el.classList.add("dragging");
        });
        el.addEventListener("dragend", () => el.classList.remove("dragging"));
      }
      col.appendChild(el);
    }

    // Click en hueco: crear tarea con esa hora (como Google Calendar)
    col.addEventListener("click", (ev) => {
      if (ev.target !== col) return;
      const y = ev.offsetY;
      const minutos = Math.floor((y / HORA_PX) * 60 / 30) * 30;
      const inicio = new Date(dia);
      inicio.setHours(Math.floor(minutos / 60), minutos % 60, 0, 0);
      abrirModalTarea({ fechaInicio: inicio, fechaFin: new Date(inicio.getTime() + 3600000) });
    });

    // Zona de soltado para mover bloques arrastrados
    col.addEventListener("dragover", (ev) => {
      if (!bloqueArrastrado) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "move";
      col.classList.add("drag-over");
    });
    col.addEventListener("dragleave", (ev) => {
      if (!ev.relatedTarget || !col.contains(ev.relatedTarget)) {
        col.classList.remove("drag-over");
      }
    });
    col.addEventListener("drop", async (ev) => {
      ev.preventDefault();
      col.classList.remove("drag-over");
      if (!bloqueArrastrado) return;
      const bloque = bloqueArrastrado;
      bloqueArrastrado = null;

      const rect = col.getBoundingClientRect();
      const duracionMin = (bloque.end - bloque.start) / 60000;
      let minutos = Math.floor(((ev.clientY - rect.top) / HORA_PX) * 60 / 15) * 15;
      minutos = Math.max(0, Math.min(minutos, 24 * 60 - duracionMin));
      const inicio = new Date(dia);
      inicio.setHours(Math.floor(minutos / 60), minutos % 60, 0, 0);

      if (inicio < new Date()) {
        toast("No se puede mover al pasado", true);
        return;
      }
      try {
        await api(`/api/horario/bloques/${bloque.id}/mover`, {
          method: "PUT",
          body: JSON.stringify({ inicio: fmt(inicio) }),
        });
        toast(`Bloque movido a ${fmtHora(inicio)}`);
        cargarTodo();
      } catch (ex) {
        toast("No se pudo mover: " + ex.message, true);
        cargarTodo();
      }
    });

    cal.appendChild(col);

    // Con la columna ya en el DOM se puede medir: limita el título de cada
    // bloque a las líneas que caben (corte limpio con puntos suspensivos;
    // el título completo vive en el tooltip y en el popover).
    for (const ev of col.querySelectorAll(".event:not(.compact)")) {
      const t = ev.querySelector(".e-title");
      const tiempo = ev.querySelector(".e-time");
      if (!t) continue;
      const linea = parseFloat(getComputedStyle(ev).lineHeight) || 15;
      const espacio = ev.clientHeight - 8 - (tiempo ? tiempo.offsetHeight : 0);
      t.style.webkitLineClamp = String(Math.max(1, Math.floor(espacio / linea)));
    }
  }
}

/** Asigna carril y cantidad de carriles a cada evento (solapes por clusters). */
function layoutEventos(ordenados) {
  let cluster = [];
  let finCluster = -1;
  const clusters = [];
  for (const e of ordenados) {
    if (cluster.length && e.start >= finCluster) {
      clusters.push(cluster);
      cluster = [];
      finCluster = -1;
    }
    cluster.push(e);
    finCluster = Math.max(finCluster, e.end);
  }
  if (cluster.length) clusters.push(cluster);

  for (const c of clusters) {
    const carriles = [];
    for (const e of c) {
      let col = carriles.findIndex(l => l[l.length - 1].end <= e.start);
      if (col === -1) { carriles.push([]); col = carriles.length - 1; }
      carriles[col].push(e);
      e.col = col;
    }
    const n = carriles.length;
    for (const e of c) e.nCarriles = n;
  }
}

// ---------------------- Mini calendario ----------------------
function renderMiniCal() {
  const cont = document.getElementById("mini-cal");
  const y = mesMini.getFullYear();
  const m = mesMini.getMonth();
  const primero = new Date(y, m, 1);
  const offset = (primero.getDay() + 6) % 7;          // lunes primero
  const diasEnMes = new Date(y, m + 1, 0).getDate();
  const hoy = new Date();

  let html = `
    <div class="mc-head">
      <div class="mc-title">${MESES[m]} ${y}</div>
      <div>
        <button class="mc-nav" data-mc="-1">&#8249;</button>
        <button class="mc-nav" data-mc="1">&#8250;</button>
      </div>
    </div>
    <div class="mc-grid">
      ${DIAS.map(d => `<div class="dow">${d[0]}</div>`).join("")}`;

  const total = Math.ceil((offset + diasEnMes) / 7) * 7;
  for (let i = 0; i < total; i++) {
    const num = i - offset + 1;
    if (num < 1 || num > diasEnMes) {
      html += `<div class="mc-day otro"></div>`;
      continue;
    }
    const fecha = new Date(y, m, num);
    let cls = "mc-day";
    if (mismaFecha(fecha, hoy)) cls += " hoy";
    if (mismaFecha(fecha, inicioVisible)) cls += " ring-start";
    if (mismaFecha(fecha, finVisible)) cls += " ring-end";
    const titulo = [];
    if (mismaFecha(fecha, inicioVisible)) titulo.push("Inicio de la vista");
    if (mismaFecha(fecha, hoy)) titulo.push("Hoy");
    if (mismaFecha(fecha, finVisible)) titulo.push("Fin de la vista");
    html += `<div class="${cls}" data-mcdia="${num}" title="${titulo.join(" · ")}">${num}</div>`;
  }
  html += `</div>`;
  cont.innerHTML = html;

  cont.querySelectorAll("[data-mc]").forEach(b =>
    b.addEventListener("click", () => {
      mesMini = new Date(y, m + Number(b.dataset.mc), 1);
      renderMiniCal();
    }));
  cont.querySelectorAll("[data-mcdia]").forEach(d => {
    d.addEventListener("click", () => {
      const fecha = new Date(y, m, Number(d.dataset.mcdia));
      const esInicio = d.classList.contains("ring-start");
      const esFin = d.classList.contains("ring-end");
      // En táctil, tocar un día con anillo mueve el anillo (selector de
      // fecha) en lugar de navegar la vista a esa semana.
      if (esTactil() && (esInicio || esFin)) {
        abrirMover({
          titulo: esInicio ? "Mover inicio de la vista" : "Mover fin de la vista",
          meta: `Elige la nueva fecha del ${esInicio ? "inicio" : "fin"}.`,
          valorInicial: fecha,
          aplicar: (f) => moverExtremo(esInicio ? "inicio" : "fin", f),
        });
        return;
      }
      inicioVisible = lunesDe(fecha);
      finVisible = new Date(inicioVisible);
      finVisible.setDate(inicioVisible.getDate() + 6);
      cargarTodo();
      guardarPreferencias();
    });
    // Las casillas con anillo también se pueden arrastrar desde el mini calendario
    if (d.classList.contains("ring-start") || d.classList.contains("ring-end")) {
      d.draggable = true;
      d.dataset.anillo = d.classList.contains("ring-start") ? "inicio" : "fin";
      d.addEventListener("dragstart", (ev) => {
        anilloArrastrado = d.dataset.anillo;
        ev.dataTransfer.setData("text/plain", d.dataset.anillo);
        ev.dataTransfer.effectAllowed = "move";
        d.classList.add("anillo-dragging");
      });
      d.addEventListener("dragend", () => {
        d.classList.remove("anillo-dragging");
        anilloArrastrado = null;
        document.querySelectorAll(".anillo-drop").forEach(el => el.classList.remove("anillo-drop"));
      });
    }
    // El mini calendario también recibe anillos arrastrados
    d.addEventListener("dragover", (ev) => {
      if (!anilloArrastrado) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "move";
      d.classList.add("anillo-drop");
    });
    d.addEventListener("dragleave", () => d.classList.remove("anillo-drop"));
    d.addEventListener("drop", (ev) => {
      ev.preventDefault();
      d.classList.remove("anillo-drop");
      if (!anilloArrastrado) return;
      moverExtremo(anilloArrastrado, new Date(y, m, Number(d.dataset.mcdia)));
    });
  });
}

// ---------------------- Lista de tareas ----------------------
/** Próximo inicio de una recurrencia estrictamente posterior a `after`.
    Devuelve un timestamp o null si la recurrencia ya terminó. */
function proxInicioRecurrente(t, after) {
  const recIni = fromFmt(t.recurrencia_inicio);
  const recFin = fromFmt(t.recurrencia_fin);
  if (!recIni || !recFin || !t.recurrencia_min) return null;
  const paso = t.recurrencia_min * 60000;
  let occ = recIni.getTime();
  const finMs = recFin.getTime();
  while (occ <= after && occ <= finMs) occ += paso;
  return occ <= finMs ? occ : null;
}

/** Estado de una tarea según su HORARIO ASIGNADO (bloques reales de
    horario_generado), no según su ventana de asignación. Una tarea está
    "en curso" solo si un bloque asignado cubre este momento; "próxima" si
    su siguiente bloque aún no empieza; "vencida" si su último bloque ya
    terminó; "sin_asignar" si nunca recibió un bloque.
    Devuelve { estado, inicio, fin, sinAsignar } o null. */
function ocurrenciaAsignada(t) {
  const now = Date.now();
  const bloques = bloquesPorTarea.get(t.id) || [];
  const enCurso = bloques.find(b => b.inicio <= now && now < b.fin);
  if (enCurso) return { estado: "curso", inicio: enCurso.inicio, fin: enCurso.fin };
  const siguiente = bloques.find(b => b.inicio > now);
  if (siguiente) return { estado: "proxima", inicio: siguiente.inicio, fin: siguiente.fin };
  if (t.es_recurrente && t.recurrencia_min && t.recurrencia_inicio && t.recurrencia_fin) {
    const occ = proxInicioRecurrente(t, now);
    if (occ !== null) return { estado: "proxima", inicio: occ, fin: null, sinAsignar: true };
    return { estado: "finalizada", inicio: null, fin: null };
  }
  if (bloques.length) {
    let ultimo = bloques[0];
    for (const b of bloques) if (b.fin > ultimo.fin) ultimo = b;
    return { estado: "vencida", inicio: ultimo.inicio, fin: ultimo.fin };
  }
  return { estado: "sin_asignar", inicio: null, fin: null };
}

/** Duraciones legibles: '45 min', '2 h 15 min', '3 d 4 h'. */
function fmtDuracion(ms) {
  const totalMin = Math.max(0, Math.ceil(ms / 60000));
  if (totalMin < 60) return `${totalMin} min`;
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h < 24) return m ? `${h} h ${m} min` : `${h} h`;
  const d = Math.floor(h / 24);
  const hr = h % 24;
  return hr ? `${d} d ${hr} h` : `${d} d`;
}

/** Etiqueta, clase de color y claves de orden según el horario asignado. */
function infoTarea(t, occ) {
  if (t.estado === "completada") return { texto: "Completada", cls: "", orden: 4, val: 0 };
  if (t.estado === "cancelada") return { texto: "Cancelada", cls: "", orden: 5, val: 0 };
  if (!occ) return { texto: "", cls: "", orden: 3, val: 0 };
  const now = Date.now();
  if (occ.estado === "curso") {
    return {
      texto: `En curso · termina en ${fmtDuracion(occ.fin - now)} · ${fmtHora(new Date(occ.inicio))} a ${fmtHora(new Date(occ.fin))}`,
      cls: "curso", orden: 0, val: occ.fin,
    };
  }
  if (occ.estado === "proxima") {
    const horas = occ.fin ? ` · ${fmtHora(new Date(occ.inicio))} a ${fmtHora(new Date(occ.fin))}` : "";
    const texto = occ.sinAsignar
      ? `Sin asignar · próxima ocurrencia en ${fmtDuracion(occ.inicio - now)}`
      : `Empieza en ${fmtDuracion(occ.inicio - now)}${horas}`;
    return { texto, cls: "proxima", orden: 1, val: occ.inicio };
  }
  if (occ.estado === "finalizada") {
    return { texto: "Recurrencia terminada", cls: "vencida", orden: 2, val: 0 };
  }
  if (occ.estado === "vencida") {
    return {
      texto: `Terminó hace ${fmtDuracion(now - occ.fin)} · ${fmtHora(new Date(occ.inicio))} a ${fmtHora(new Date(occ.fin))}`,
      cls: "vencida", orden: 2, val: -occ.fin,
    };
  }
  const iniVentana = fromFmt(t.fecha_inicio);
  return { texto: "Sin asignar", cls: "", orden: 3, val: iniVentana ? iniVentana.getTime() : 0 };
}

function renderListaTareas() {
  const cont = document.getElementById("task-list");
  if (!tareas.length) {
    cont.innerHTML = `<div style="padding:6px 10px;color:#70757a;font-size:12.5px;">Sin tareas todavía.</div>`;
    return;
  }
  const conInfo = tareas.map(t => ({ t, occ: null, info: null }));
  for (const c of conInfo) {
    c.occ = c.t.estado === "pendiente" ? ocurrenciaAsignada(c.t) : null;
    c.info = infoTarea(c.t, c.occ);
  }
  // Orden por cercanía a la hora actual según el horario asignado:
  // en curso (por fin más próximo), próximas (por inicio más cercano),
  // vencidas (por fin más reciente), sin asignar, y al final completadas
  // y canceladas.
  conInfo.sort((a, b) =>
    (a.info.orden - b.info.orden) ||
    (a.info.val - b.info.val) ||
    ((a.t.prioridad || 3) - (b.t.prioridad || 3)) ||
    a.t.titulo.localeCompare(b.t.titulo)
  );

  cont.innerHTML = "";
  for (const { t, occ, info } of conInfo) {
    const item = document.createElement("div");
    item.className = "task-item" + (t.estado === "completada" ? " done" : "");
    // Solo se puede marcar completada si su horario asignado ya pasó por
    // completo: su último bloque terminó o su recurrencia terminó.
    const puedeCompletar = t.estado === "completada" ||
      (t.estado === "pendiente" && occ && (occ.estado === "vencida" || occ.estado === "finalizada"));
    let tituloCheck;
    if (t.estado === "completada") tituloCheck = "Marcar pendiente";
    else if (t.estado === "cancelada") tituloCheck = "Tarea cancelada";
    else if (puedeCompletar) tituloCheck = "Marcar completada";
    else tituloCheck = "Solo se puede completar cuando su horario asignado haya pasado por completo";
    item.innerHTML = `
      <button class="t-check" title="${tituloCheck}"></button>
      <span class="t-dot prio-${t.prioridad || 3}"></span>
      <span class="t-body">
        <span class="t-title" title="${escapeHtml(t.titulo)}">${escapeHtml(t.titulo)}</span>
        <span class="t-time ${info.cls}">${escapeHtml(info.texto)}</span>
      </span>`;
    const check = item.querySelector(".t-check");
    if (!puedeCompletar) check.disabled = true;
    check.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const nuevo = t.estado === "completada" ? "pendiente" : "completada";
      try {
        await api(`/api/tareas/${t.id}/estado`, { method: "POST", body: JSON.stringify({ estado: nuevo }) });
        toast(nuevo === "completada" ? "Tarea completada" : "Tarea reactivada");
      } catch (ex) {
        toast("Error: " + ex.message, true);
      }
      cargarTodo();
    });
    item.addEventListener("click", () => abrirModalTarea({ tarea: t }));
    cont.appendChild(item);
  }
}

function renderNoProgramadas(lista) {
  document.getElementById("np-count").textContent = lista.length;
  document.getElementById("np-row").onclick = () => {
    if (!lista.length) { toast("Sin tareas pendientes de espacio"); return; }
    const cont = document.getElementById("np-list");
    cont.innerHTML = lista.map(n => `
      <div class="np-item">
        <div class="np-title">${escapeHtml(n.titulo || `Tarea #${n.tarea_id}`)}</div>
        <div class="np-meta">${escapeHtml(n.motivo || "")} · faltan ${n.duracion_faltante_min ?? "?"} min</div>
      </div>`).join("");
    document.getElementById("np-overlay").classList.remove("hidden");
  };
}

// ---------------------- Modal crear / editar ----------------------
function abrirModalTarea({ tarea = null, fechaInicio = null, fechaFin = null } = {}) {
  tareaEditandoId = tarea ? tarea.id : null;
  document.getElementById("modal-title").textContent = tarea ? "Editar tarea" : "Nueva tarea";

  document.getElementById("f-titulo").value = tarea ? tarea.titulo : "";
  document.getElementById("f-descripcion").value = tarea ? (tarea.descripcion || "") : "";
  document.getElementById("f-duracion").value = tarea ? tarea.duracion_min : 60;
  document.getElementById("f-prioridad").value = tarea ? String(tarea.prioridad || 3) : "3";
  document.getElementById("f-bloque-entero").checked = tarea ? Boolean(tarea.bloque_entero) : false;

  const ini = tarea ? fromFmt(tarea.fecha_inicio) : (fechaInicio || new Date(Date.now() + 3600000));
  const fin = tarea ? fromFmt(tarea.fecha_fin) : (fechaFin || new Date(ini.getTime() + 3600000));
  document.getElementById("f-inicio").value = toLocalInput(ini);
  document.getElementById("f-fin").value = toLocalInput(fin);

  const repite = tarea && tarea.es_recurrente ? String(tarea.recurrencia_min) : "none";
  document.getElementById("f-repetir").value = repite;
  const hasta = tarea && tarea.es_recurrente && tarea.recurrencia_fin
    ? toLocalInput(fromFmt(tarea.recurrencia_fin))
    : toLocalInput(new Date(fin.getTime() + 28 * 86400000));
  document.getElementById("f-hasta").value = hasta;
  document.getElementById("f-hasta-wrap").classList.toggle("hidden", repite === "none");

  document.getElementById("modal-overlay").classList.remove("hidden");
  document.getElementById("f-titulo").focus();
}

function cerrarModalTarea() {
  document.getElementById("modal-overlay").classList.add("hidden");
}

function datosDelFormulario() {
  const ini = fromLocalInput(document.getElementById("f-inicio").value);
  const fin = fromLocalInput(document.getElementById("f-fin").value);
  const repite = document.getElementById("f-repetir").value;
  const esRecurrente = repite !== "none";
  return {
    titulo: document.getElementById("f-titulo").value.trim(),
    descripcion: document.getElementById("f-descripcion").value.trim(),
    duracion_min: parseInt(document.getElementById("f-duracion").value, 10),
    prioridad: parseInt(document.getElementById("f-prioridad").value, 10),
    bloque_entero: document.getElementById("f-bloque-entero").checked,
    fecha_inicio: fmt(ini),
    fecha_fin: fmt(fin),
    es_recurrente: esRecurrente,
    recurrencia_min: esRecurrente ? parseInt(repite, 10) : null,
    recurrencia_inicio: esRecurrente ? fmt(ini) : null,
    recurrencia_fin: esRecurrente ? fmt(fromLocalInput(document.getElementById("f-hasta").value)) : null,
  };
}

async function guardarTarea(ev) {
  ev.preventDefault();
  const datos = datosDelFormulario();
  try {
    if (tareaEditandoId) {
      await api(`/api/tareas/${tareaEditandoId}`, { method: "PUT", body: JSON.stringify(datos) });
      toast("Tarea actualizada");
    } else {
      await api("/api/tareas", { method: "POST", body: JSON.stringify(datos) });
      toast("Tarea creada. Pulsa 'Generar horario' para agendarla.");
    }
    cerrarModalTarea();
    cargarTodo();
  } catch (ex) {
    toast("Error: " + ex.message, true);
  }
}

// ---------------------- Popover de evento ----------------------
function abrirPopover(ev, bloque) {
  const pop = document.getElementById("popover");
  const tarea = tareas.find(t => t.id === bloque.tarea_id);
  const futuro = bloque.end > new Date();
  const sinCompletar = futuro && !bloque.completado;
  pop.innerHTML = `
    <div class="p-title">${escapeHtml(bloque.titulo)}</div>
    <div class="p-meta">
      ${DIAS_LARGO[(bloque.start.getDay() + 6) % 7]} ${bloque.start.getDate()} · ${fmtRango(bloque.start, bloque.end)}
      <br>Prioridad: ${PRIO_NOMBRE[bloque.prioridad] || bloque.prioridad}
      ${bloque.fijado ? "<br>Bloque movido a mano" : ""}
      ${bloque.completado ? "<br><b>Completado</b>" : ""}
    </div>
    ${bloque.es_recurrente ? `<div class="p-lock-note">${ICONO_RECURRENCIA} Bloque recurrente: solo se mueve dentro de su ventana${bloque.ventana_inicio ? ` (del ${fmtVentana(bloque.ventana_inicio, bloque.ventana_fin)})` : ""}</div>` : ""}
    ${sinCompletar ? `<div class="p-lock-note">${ICONO_RELOJ} No se puede completar: la actividad aún no termina</div>` : ""}
    <div class="p-actions">
      ${sinCompletar ? "" : `<button class="p-act" data-act="toggle">${ICONO_CHECK} ${bloque.completado ? "Marcar pendiente" : "Marcar completado"}</button>`}
      ${!bloque.completado ? `<button class="p-act" data-act="mover">${ICONO_MOVER} Mover</button>` : ""}
      ${tarea ? `<button class="p-act" data-act="editar">${ICONO_LAPIZ} Editar tarea</button>` : ""}
      <button class="p-act danger" data-act="eliminar">${ICONO_PAPELERA} Eliminar bloque</button>
    </div>
    ${!bloque.completado ? `<div class="p-hint">${ICONO_MOVER} Arrastra el bloque o pulsa Mover para cambiarlo de hora${bloque.es_recurrente ? " (recurrente: solo dentro de su ventana)" : ""}</div>` : ""}`;

  const movil = window.innerWidth <= 480;
  const rect = ev.target.getBoundingClientRect();
  if (movil) {
    // Hoja inferior tipo app móvil: ancho completo, pegada abajo.
    pop.style.left = "8px";
    pop.style.right = "8px";
    pop.style.width = "auto";
    pop.style.top = "auto";
    pop.style.bottom = "8px";
  } else {
    pop.style.right = "auto";
    pop.style.bottom = "auto";
    pop.style.width = "300px";
    const x = Math.min(rect.left, window.innerWidth - 320);
    const y = Math.min(rect.top + 10, window.innerHeight - 240);
    pop.style.left = `${Math.max(x, 8)}px`;
    pop.style.top = `${Math.max(y, 8)}px`;
  }
  pop.classList.remove("hidden");

  pop.querySelectorAll("[data-act]").forEach(b => {
    b.onclick = async () => {
      const act = b.dataset.act;
      if (act === "toggle") {
        await api(`/api/horario/bloques/${bloque.id}`, {
          method: "PATCH", body: JSON.stringify({ completado: !bloque.completado }),
        });
        toast(bloque.completado ? "Bloque marcado pendiente" : "Bloque completado");
      } else if (act === "mover") {
        cerrarPopover();
        abrirMover({
          titulo: "Mover bloque",
          meta: `Se conserva su duración. Horario actual: ${fmtRango(bloque.start, bloque.end)}.` +
            (bloque.es_recurrente && bloque.ventana_inicio
              ? ` Ventana permitida: ${fmtVentana(bloque.ventana_inicio, bloque.ventana_fin)}.` : ""),
          valorInicial: bloque.start,
          aplicar: async (inicio) => {
            try {
              await api(`/api/horario/bloques/${bloque.id}/mover`, {
                method: "PUT",
                body: JSON.stringify({ inicio: fmt(inicio) }),
              });
              toast(`Bloque movido a ${fmtHora(inicio)}`);
              cargarTodo();
            } catch (ex) {
              toast("No se pudo mover: " + ex.message, true);
            }
          },
        });
        return;
      } else if (act === "editar" && tarea) {
        abrirModalTarea({ tarea });
      } else if (act === "eliminar") {
        if (!confirm("¿Eliminar este bloque del horario?")) return;
        await api(`/api/horario/bloques/${bloque.id}`, { method: "DELETE" });
        toast("Bloque eliminado");
      }
      cerrarPopover();
      cargarTodo();
    };
  });
}

function cerrarPopover() {
  document.getElementById("popover").classList.add("hidden");
}

// ---------------------- Modal de mover (táctil) ----------------------
let moverAplicar = null;

/** Abre el selector de fecha para mover un bloque o un anillo de la vista.
    `aplicar(fecha)` se llama al confirmar. */
function abrirMover({ titulo, meta = "", valorInicial, aplicar }) {
  moverAplicar = aplicar;
  document.getElementById("mover-titulo").textContent = titulo;
  document.getElementById("mover-meta").textContent = meta;
  document.getElementById("mover-fecha").value = toLocalInput(valorInicial || new Date());
  document.getElementById("mover-overlay").classList.remove("hidden");
  document.getElementById("mover-fecha").focus();
}

function cerrarMover() {
  moverAplicar = null;
  document.getElementById("mover-overlay").classList.add("hidden");
}

// ---------------------- Drawer lateral (móvil) ----------------------
function abrirDrawer() {
  document.body.classList.add("drawer-open");
  document.getElementById("drawer-backdrop").classList.remove("hidden");
}

function cerrarDrawer() {
  document.body.classList.remove("drawer-open");
  document.getElementById("drawer-backdrop").classList.add("hidden");
}

// ---------------------- Toast ----------------------
let toastTimer = null;
function toast(mensaje, esError = false) {
  const el = document.getElementById("toast");
  el.textContent = mensaje;
  el.className = "toast" + (esError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 4000);
}

// ---------------------- Utilidades ----------------------
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------------------- Eventos globales ----------------------
async function init() {
  const me = await api("/api/auth/me").catch(() => null);
  if (!me || !me.autenticado) { location.href = "/"; return; }

  // Preferencias persistidas en el servidor (tema y posición de los anillos)
  const prefs = await api("/api/preferencias").catch(() => null);
  if (prefs && (prefs.tema === "oscuro" || prefs.tema === "claro")) {
    document.documentElement.dataset.theme = prefs.tema;
    localStorage.setItem("tema", prefs.tema);
  }
  if (prefs) {
    const iniPref = parseDiaISO(prefs.inicio_visible);
    const finPref = parseDiaISO(prefs.fin_visible);
    if (iniPref && finPref && iniPref < finPref) {
      inicioVisible = iniPref;
      finVisible = finPref;
    }
  }

  // Modo oscuro (switch simple, persistido en el servidor)
  const btnTema = document.getElementById("btn-tema");
  const temaGuardado = document.documentElement.dataset.theme || localStorage.getItem("tema") || "claro";
  document.documentElement.dataset.theme = temaGuardado;
  btnTema.title = temaGuardado === "oscuro" ? "Cambiar a modo claro" : "Cambiar a modo oscuro";
  btnTema.onclick = () => {
    const actual = document.documentElement.dataset.theme === "oscuro" ? "claro" : "oscuro";
    document.documentElement.dataset.theme = actual;
    localStorage.setItem("tema", actual);
    btnTema.title = actual === "oscuro" ? "Cambiar a modo claro" : "Cambiar a modo oscuro";
    guardarPreferencias();
  };

  document.getElementById("btn-prev").onclick = () => {
    inicioVisible.setDate(inicioVisible.getDate() - 7);
    finVisible.setDate(finVisible.getDate() - 7);
    cargarTodo();
    guardarPreferencias();
  };
  document.getElementById("btn-next").onclick = () => {
    inicioVisible.setDate(inicioVisible.getDate() + 7);
    finVisible.setDate(finVisible.getDate() + 7);
    cargarTodo();
    guardarPreferencias();
  };
  document.getElementById("btn-hoy").onclick = () => {
    inicioVisible = lunesDe(new Date());
    finVisible = new Date(inicioVisible);
    finVisible.setDate(finVisible.getDate() + 6);
    mesMini = new Date();
    cargarTodo();
    guardarPreferencias();
  };
  document.getElementById("btn-crear").onclick = () => abrirModalTarea();
  document.getElementById("btn-cancelar").onclick = cerrarModalTarea;
  document.getElementById("btn-guardar").onclick = guardarTarea;
  document.getElementById("task-form").addEventListener("submit", guardarTarea);

  // Modal de mover (bloques y anillos en pantallas táctiles)
  document.getElementById("mover-cancelar").onclick = cerrarMover;
  document.getElementById("mover-guardar").onclick = async () => {
    const fecha = fromLocalInput(document.getElementById("mover-fecha").value);
    if (!fecha) { toast("Elige una fecha y hora válidas", true); return; }
    const aplicar = moverAplicar;
    cerrarMover();
    if (aplicar) await aplicar(fecha);
  };
  document.getElementById("mover-overlay").addEventListener("click", (e) => {
    if (e.target.id === "mover-overlay") cerrarMover();
  });

  // Drawer lateral en móvil
  document.getElementById("btn-tareas").onclick = () => {
    if (document.body.classList.contains("drawer-open")) cerrarDrawer();
    else abrirDrawer();
  };
  document.getElementById("drawer-backdrop").onclick = cerrarDrawer;
  // Al elegir una tarea o un día del mini calendario dentro del drawer,
  // se cierra para volver a la vista principal.
  document.getElementById("sidebar").addEventListener("click", (e) => {
    if (e.target.closest(".task-item") || e.target.closest("[data-mcdia]")) cerrarDrawer();
  });
  // Si la ventana vuelve a tamaño de escritorio, el drawer no debe quedar
  // abierto en un estado que el CSS ya no muestra.
  window.matchMedia("(min-width: 901px)").addEventListener("change", (mq) => {
    if (mq.matches) cerrarDrawer();
  });
  document.getElementById("modal-overlay").addEventListener("click", (e) => {
    if (e.target.id === "modal-overlay") cerrarModalTarea();
  });
  document.getElementById("np-cerrar").onclick = () => document.getElementById("np-overlay").classList.add("hidden");
  document.getElementById("f-repetir").addEventListener("change", (e) => {
    document.getElementById("f-hasta-wrap").classList.toggle("hidden", e.target.value === "none");
  });
  document.getElementById("btn-logout").onclick = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => null);
    location.href = "/";
  };
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#popover") && !e.target.closest(".event")) cerrarPopover();
  });

  // Generar horario (botón primario)
  const btnGen = document.getElementById("btn-generar");
  const lblGen = document.getElementById("gen-label");
  btnGen.onclick = async () => {
    btnGen.disabled = true;
    lblGen.innerHTML = `<span class="spin"></span>Generando…`;
    try {
      const r = await api("/api/horario/generar", { method: "POST" });
      toast(r.mensaje || "Horario generado");
    } catch (ex) {
      toast("Error: " + ex.message, true);
    } finally {
      btnGen.disabled = false;
      lblGen.textContent = "Generar horario";
      cargarTodo();
    }
  };

  // Descargar el horario visible como PDF de una hoja
  document.getElementById("btn-descargar").onclick = () => {
    const soloFecha = d =>
      d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
      "-" + String(d.getDate()).padStart(2, "0");
    const finExclusivo = new Date(finVisible);
    finExclusivo.setDate(finExclusivo.getDate() + 1);
    const url =
      "/api/horario/pdf?inicio=" + encodeURIComponent(soloFecha(inicioVisible)) +
      "&fin=" + encodeURIComponent(soloFecha(finExclusivo));
    const enlace = document.createElement("a");
    enlace.href = url;
    enlace.download = "horario_" + soloFecha(inicioVisible) + "_al_" + soloFecha(finVisible) + ".pdf";
    document.body.appendChild(enlace);
    enlace.click();
    enlace.remove();
    toast("Descargando el horario en PDF…");
  };

  cargarTodo();
  // Sincroniza al servidor el estado actual (tema del navegador y vista)
  if (prefs) guardarPreferencias();

  // Línea "ahora" se refresca cada minuto si hoy está en la vista
  setInterval(() => {
    const hoy = new Date();
    const finDia = new Date(finVisible);
    finDia.setDate(finDia.getDate() + 1);
    if (hoy >= inicioVisible && hoy < finDia) cargarTodo();
  }, 60000);
}

document.addEventListener("DOMContentLoaded", init);
