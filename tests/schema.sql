CREATE TABLE tareas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    descripcion TEXT,
    estado TEXT DEFAULT 'pendiente' CHECK(estado IN ('pendiente','completada','cancelada')),
    
    -- 1 = máxima prioridad, 4 = baja (por defecto 3)
    prioridad INTEGER DEFAULT 3 CHECK(prioridad >= 1),

    -- Ventana flexible
    fecha_inicio TIMESTAMP NOT NULL,   -- inicio de la ventana
    fecha_fin TIMESTAMP NOT NULL,      -- fin de la ventana
    duracion_min INTEGER NOT NULL,     -- minutos totales a dedicar

    -- ¿Debe realizarse en un solo bloque continuo?
    bloque_entero BOOLEAN DEFAULT TRUE,     -- TRUE = bloque único obligatorio, FALSE = se puede fraccionar

    -- Recurrencia (opcional)
    es_recurrente BOOLEAN DEFAULT FALSE,
    recurrencia_min INTEGER,           -- minutos entre repeticiones
    recurrencia_inicio TIMESTAMP,      -- desde cuándo se repite
    recurrencia_fin TIMESTAMP,         -- límite máximo

    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE horario_generado (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tarea_id INTEGER NOT NULL,
    inicio TIMESTAMP NOT NULL,         -- fecha/hora de comienzo del bloque
    fin TIMESTAMP NOT NULL,            -- fecha/hora de finalización del bloque
    completado BOOLEAN DEFAULT FALSE,  -- si ese bloque concreto ya se realizó
    fijado BOOLEAN DEFAULT FALSE,      -- TRUE = movido a mano, se conserva al regenerar
    FOREIGN KEY (tarea_id) REFERENCES tareas(id) ON DELETE CASCADE
);
CREATE TABLE tareas_no_programadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tarea_id INTEGER NOT NULL,
    fecha_intento TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    motivo TEXT NOT NULL DEFAULT 'falta de tiempo',
    duracion_faltante_min INTEGER NOT NULL DEFAULT 0,   -- minutos que no se pudieron asignar
    detalles TEXT,                                      -- info extra (JSON con ventana intentada, conflictos, etc.)
    FOREIGN KEY (tarea_id) REFERENCES tareas(id) ON DELETE CASCADE
);