# Gestor de Tareas (versión web)

Aplicación web para planificar tareas con un motor propio de organización
automática del tiempo. Interfaz inspirada en Google Calendar.

El motor de planificación es propio del proyecto y vive en
`app/services/planificador.py`; la aplicación web lo usa como servicio y
añade encima:

- Interfaz web tipo Google Calendar (vista semanal, mini calendario, modal
  de tareas con repeticiones, popover por bloque).
- Login simple de un solo usuario (contraseña en `.env`).
- Base de datos dual: SQLite local o Turso (nube), configurable por
  variables de entorno sin tocar código.
- API REST (FastAPI) + suite de pruebas completa.
- Modo oscuro con interruptor y posición de la vista (anillos verde y rojo)
  persistidos en la base de datos, no solo en el navegador.
- Iconos SVG modernos (sin emojis).
- Marcadores de la vista: anillo de inicio (verde), hoy y anillo de fin (rojo),
  tanto en la cabecera como en el mini calendario. El verde y el rojo se
  arrastran a cualquier día, desde la cabecera o desde el propio mini
  calendario, para definir un rango
  personalizado de 2 a 28 días, por ejemplo de sábado a lunes; el inicio debe
  ser siempre anterior al fin. Los botones de la barra superior mueven el rango
  completo por semana y «Hoy» lo restaura a la semana actual.
- Gestión manual del horario: arrastra un bloque y suéltalo en otro hueco
  para moverlo (se ajusta a bloques de 15 min). Los bloques recurrentes
  también se pueden mover, pero solo dentro de la ventana de su ocurrencia
  (la ventana fecha inicio - fecha fin de la tarea, desplazada con cada
  repetición): las actividades con ventana exacta, como las clases, no
  tienen holgura y no se pueden posponer, mientras que las de ventana
  ancha (pre-estudio, post-estudio) sí. Los bloques movidos a mano quedan
  fijados y el motor los respeta al regenerar (no los reubica ni duplica
  su tiempo).
- Adaptación móvil: por debajo de 900 px el panel de «Mis tareas» se
  convierte en un drawer que se desliza desde la izquierda con el botón de
  lista de la barra superior. Los controles crecen a una zona táctil mínima
  de 40 px, el modal de tareas pasa a pantalla completa con las fechas
  apiladas y los inputs usan 16 px para que iOS no haga zoom automático.
  En táctil no existe el arrastre HTML5, así que los bloques se mueven con
  la acción «Mover» de su popover y los anillos tocando el anillo del día;
  ambas opciones abren un selector de fecha. Las barras de desplazamiento
  también siguen el tema: en modo oscuro usan grises oscuros.
- Descarga en PDF (botón «Descargar»): genera una única lámina grande de
  tamaño personalizado estilo infografía (no A4): cada día tiene una
  columna de 150 pt y cada hora 72 pt de alto (para que los bloques no se
  solapen), con títulos en 12 pt, para leerlos completos sin forzar la
  vista. La columna izquierda muestra las horas como reloj («00:00»,
  «01:00», ... «23:00») bajo un rótulo HORA. El ancho de la lámina crece
  con el número de días del rango elegido (el mismo que se ve en pantalla).
  El formato es el del generador de Excel del proyecto: días como columnas,
  horas como filas, colores por prioridad, carriles cuando hay solapes y
  bloques que cruzan medianoche cortados en su día. El texto es vectorial (nítido
  al ampliar) y el título de cada actividad se dibuja siempre completo y
  dentro de su bloque (72 pt por hora deja sitio incluso para títulos en
  mayúsculas en bloques de 45 minutos), con sus horas de inicio y fin; en
  casos extremos el texto puede salirse del cuadro antes que perder el
  título, y los textos se dibujan después de los cuadros para que ninguno
  quede tapado. En la página web los títulos largos se recortan por líneas
  completas con puntos suspensivos (el título entero queda en el tooltip y
  en el popover), para que nunca se solapen con el bloque de abajo.
- Bloques nocturnos: una actividad que cruza medianoche (por ejemplo
  «Dormir» de 23:00 a 05:00) se dibuja cortada en la línea de medianoche:
  el tramo 23:00 a 24:00 al fondo de su día y la madrugada 00:00 a 05:00
  arriba del día siguiente.
- «Mis tareas» ordenada por cercanía a la hora actual según el horario
  asignado de cada tarea (el bloque real que le puso el planificador), no
  según su ventana de asignación: primero las que están en curso (solo si
  un bloque asignado cubre este momento, con los minutos que faltan para
  terminar), luego las que están por empezar (con los minutos que faltan
  para su inicio), después las vencidas, las que aún no tienen bloque
  asignado y al final completadas y canceladas. Cada etiqueta muestra la
  hora realmente asignada. Una tarea solo se puede marcar como Completada
  cuando su horario asignado ya pasó por completo; las pendientes que
  viven en el pasado desaparecen del calendario al presionar «Generar
  horario»: se siente como si se hubieran movido más adelante en el
  tiempo (los que tienen ventana se re-agendan en lo que les queda, y los
  de ventana vencida se van porque su siguiente repetición ya está
  agendada). Los bloques en curso sin completar también se reubican hacia
  delante: el botón siempre deja todo agendado desde ahora.
- Completar solo en el pasado, también en el calendario: un bloque futuro
  no se puede marcar como completado. El popover esconde el botón y
  muestra un aviso mientras la actividad no termina, y la API lo rechaza
  con 422. Desmarcar (volver a pendiente) sí se permite siempre.

---

## Requisitos

- Python 3.11 o superior (solo se usan dependencias puras de Python:
  FastAPI, uvicorn, pydantic, itsdangerous, httpx/pytest para pruebas).
- Turso se accede por su API HTTP oficial (`/v2/pipeline`, protocolo
  Hrana), implementada con la librería estándar en `app/db.py`; no
  requiere ningún cliente externo ni soporte de websockets.

## Instalación

```bash
# 1. Crear entorno virtual e instalar dependencias
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows
# (en Linux/Mac: source .venv/bin/activate && pip install -r requirements.txt)

# 2. Crear el archivo de configuración
cp .env.example .env
# editar .env: definir APP_PASSWORD (contraseña de ingreso)

# 3. Arrancar
python run.py
# -> http://127.0.0.1:8000
```

## Configuración (.env)

| Variable | Descripción | Valor por defecto |
| --- | --- | --- |
| `APP_PASSWORD` | Contraseña para entrar a la web | (obligatoria) |
| `DB_MODE` | `local` (SQLite) o `turso` (nube) | `local` |
| `DB_PATH` | Archivo SQLite local | `data/app.db` |
| `TURSO_URL` | URL de la base Turso (`libsql://...`) | — |
| `TURSO_AUTH_TOKEN` | Token de autenticación de Turso | — |
| `HORIZONTE_DIAS` | Días hacia delante que planifica el motor | `7` |

Con `DB_MODE=turso` la app se conecta automáticamente a Turso; sin
cambiar nada usa SQLite local.

## Cómo funciona el motor

`app/services/planificador.py` implementa el motor de planificación del
proyecto. Reglas principales:

- Ventana flexible por tarea (`fecha_inicio` / `fecha_fin`), duración en
  minutos y prioridad (1 máxima, 5 mínima).
- `bloque_entero`: la tarea no se divide; si no hay hueco continuo
  suficiente, se registra en `tareas_no_programadas` con el motivo.
- Tareas flexibles largas: ciclos de concentración de 90 min, máximo 3
  ciclos seguidos por tarea antes de dar turno a otras.
- Recurrencia: cada `recurrencia_min` minutos entre `recurrencia_inicio`
  y `recurrencia_fin`, generando una ocurrencia por ventana.
- Regla de descanso: tras un bloque de 90+ min se reservan 10 min de
  descanso; entre ciclos de la misma tarea solo si la ventana sigue
  pudiendo contenerla completa.
- Regeneración completa: al generar, se borran los bloques futuros y se
  re-planifica desde ahora; los bloques pasados se conservan como historia
  (los pendientes y los que quedaron en curso se reubican al futuro).
- Reorganización de tareas atrasadas: al generar, todos los bloques sin
  completar que ya empezaron (pasados y en curso) se borran del
  calendario y se reubican hacia delante: los que todavía tienen ventana
  se vuelven a agendar dentro de ella (también los recurrentes, dentro de
  su ocurrencia), y los de ventana vencida desaparecen porque su siguiente
  repetición queda agendada. Los bloques completados se conservan como
  historia y los fijados no se tocan. Las no recurrentes que ya terminaron
  por completo se reubican a partir de ahora conservando la duración de su
  ventana.
- Bloques fijados (movidos a mano): sobreviven a la regeneración, ocupan
  su hueco frente a otras tareas y su duración se descuenta de la tarea
  para no agendar el mismo trabajo dos veces (aunque queden a caballo del
  borde de la ventana).

## Pruebas

```bash
.venv/Scripts/python -m pytest tests/ -v
```

- `tests/test_planificador.py`: los 38 tests del motor (portados sin cambios
  de lógica) más la regla de descanso.
- `tests/test_api_*.py`: login, CRUD de tareas, generación de horario y
  bloques vía HTTP.

## Estructura

```
app/
  main.py              Punto de entrada FastAPI (monta routers y estáticos)
  config.py            Configuración desde .env
  db.py                Capa de datos dual SQLite/Turso
  security.py          Cookie de sesión firmada (itsdangerous)
  deps.py              Dependencias de autenticación
  schemas.py           Modelos Pydantic de entrada/salida
  services/
    planificador.py    Motor de planificación (reglas + descansos)
    horario_service.py Generación con "sandbox + diff" (portátil SQLite/Turso)
    tareas_service.py  CRUD y validaciones de negocio
  routers/
    auth.py            /api/auth/*
    tareas.py          /api/tareas/*
    horario.py         /api/horario/*
static/                Frontend (login, calendario, estilos)
tests/                 Suite completa
```

## API resumida

| Método | Ruta | Descripción |
| --- | --- | --- |
| POST | `/api/auth/login` | Inicia sesión `{password}` (cookie) |
| POST | `/api/auth/logout` | Cierra sesión |
| GET | `/api/auth/me` | Estado de la sesión |
| GET/POST | `/api/tareas` | Listar / crear tareas |
| GET/PUT/DELETE | `/api/tareas/{id}` | Obtener / editar / eliminar |
| POST | `/api/tareas/{id}/estado` | Cambiar estado `{estado}` (solo permite `completada` si el horario asignado de la tarea ya pasó por completo) |
| GET | `/api/tareas/no-programadas` | Tareas sin espacio |
| POST | `/api/horario/generar` | Ejecuta el motor |
| GET | `/api/horario/bloques?inicio=&fin=` | Bloques del calendario |
| PATCH | `/api/horario/bloques/{id}` | Marcar completado/pendiente (solo permite `completado` si el horario del bloque ya pasó por completo; los bloques futuros devuelven 422) |
| PUT | `/api/horario/bloques/{id}/mover` | Mover un bloque `{inicio}` (rechaza completados, destinos en el pasado o con solape; los recurrentes solo se mueven dentro de la ventana de su tarea; marca el bloque como fijado) |
| DELETE | `/api/horario/bloques/{id}` | Eliminar un bloque |
| GET/PUT | `/api/preferencias` | Leer / guardar preferencias `{tema, inicio_visible, fin_visible}` (clave-valor persistido en la base de datos) |

Fechas en formato `"YYYY-MM-DD HH:MM:SS"` (hora local).
