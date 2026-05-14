# Proyecto Final — Administración de Bases de Datos
## Estimación del Potencial Solar en Municipios PDET de Colombia
### Resumen Ejecutivo

**Curso:** Administración de Bases de Datos  
**Docente:** Andrés Oswaldo Calderón Romero, Ph.D.  
**Fecha de actualización:** Mayo 2026

---

## 1. Contexto y Objetivo

La Unidad de Planeación Minero Energética (UPME) busca identificar ubicaciones
potenciales para proyectos piloto de energía solar en Colombia. El criterio
principal de priorización son los territorios **PDET** (*Programas de Desarrollo
con Enfoque Territorial*, Decreto Ley 893 de 2017): 170 municipios en zonas de
posconflicto que requieren inversión en infraestructura.

El objetivo del proyecto es estimar, para cada uno de estos 170 municipios:

- **Número de edificaciones** presentes en su territorio.
- **Área total de tejados** (en m²) disponible para instalación de paneles solares.

Se comparan dos fuentes de datos abiertos de huellas de edificios
(Microsoft Bing y Google Open Buildings) mediante una arquitectura NoSQL
reproducible sobre MongoDB.

---

## 2. Arquitectura Tecnológica

El proyecto utiliza **MongoDB 7** como motor NoSQL principal, desplegado en
Docker junto con Mongo Express para visualización. La elección de MongoDB
sobre otras alternativas NoSQL se justifica por:

| Criterio | Justificación |
|---|---|
| GeoJSON nativo | Almacena polígonos sin conversión; el índice `2dsphere` responde `$geoWithin` / `$geoIntersects` sin extensiones externas |
| Grain documento-edificio | Coincide con el formato de los datasets (un registro = un edificio) |
| Framework de agregación | Permite el pipeline completo en el motor, sin fan-out en aplicación |
| Escala adecuada | 2-4 millones de edificios en PDET caben en un solo contenedor |

PostGIS sería el estándar de la industria para este tipo de análisis, pero
queda fuera del alcance por el requerimiento explícito de solución NoSQL.

### Modelo de datos

Tres colecciones con validadores `$jsonSchema` instalados vía `init.js`:

```
upme.municipalities     170 documentos   Polígonos PDET con área precomputada
upme.buildings_ms       ~2-4M docs       Huellas Microsoft (por cargar - Semana 3)
upme.buildings_google   ~1-3M docs       Huellas Google   (por cargar - Semana 3)
upme.results            ~340 docs        Agregados por (municipio, fuente)
```

**Decisión clave de CRS:**
- Geometría almacenada en **EPSG:4326** (WGS84), requerido por el índice `2dsphere`.
- Área (`area_sqm`) precomputada en **EPSG:9377** (MAGNA-SIRGAS Origen Nacional),
  la proyección de igual área oficial de Colombia (IGAC), y almacenada como número.
  Las consultas analíticas nunca necesitan reproyectar.

---

## 3. Progreso por Semana

### Semana 1 — Diseño del Esquema NoSQL ✅

**Entregable:** Plan de implementación, modelo de datos y esquema.

Archivos clave:
- `semana_1/data-model.md` — Justificación de MongoDB, estrategia de CRS, plan de índices, decisión de colecciones separadas por fuente.
- `semana_1/init.js` — Crea colecciones, validadores `$jsonSchema` e índices. Idempotente.
- `semana_1/smoke_load.js` — Prueba end-to-end con datos sintéticos: inserta un municipio falso, ~1400 edificios, ejecuta el join espacial y la agregación completa.
- `compartido/schema/*.schema.json` — Contratos de esquema (fuente de verdad para validadores y revisión de código).

**Resultado del smoke test:**
El pipeline completo funciona con datos sintéticos: los validadores rechazan
documentos malformados, el índice `2dsphere` responde `$geoWithin`, el ETL
de join etiqueta edificios con su `divipola` contenedor, y la agregación
produce conteos y áreas por municipio y fuente.

---

### Semana 2 — Integración de Límites PDET ✅

**Entregable:** 170 municipios PDET cargados en MongoDB con índice espacial.

Archivos clave:
- `semana_2/informe_semana2.md` / `.pdf` — Informe completo de la entrega.
- `semana_2/metodologia_carga_pdet.md` — Metodología detallada con decisiones de diseño.
- `semana_2/validacion_datos.md` — Log de validación autogenerado (11 checks).
- `semana_2/validate_pdet.py` — Valida y emite `data/processed/pdet_municipios.geojson`.
- `semana_2/load_municipalities.py` — Upserta los 170 polígonos en MongoDB.
- `semana_2/verify_schema_validator.js` — Demuestra que el validador rechaza inserts malformados.
- `semana_2/generate_map.py` — Genera mapa PNG por subregión PDET.

**Fuentes de datos:**
| Dataset | Proveedor | Rol |
|---|---|---|
| MGN 2025 | DANE | Polígonos de los 1,122 municipios colombianos (EPSG:4326) |
| MunicipiosPDET.xlsx | ART | Lista legal de 170 municipios PDET (Decreto 893/2017) |

**Resultados verificados:**
- 170/170 códigos DIVIPOLA encontrados en el MGN (cero huérfanos).
- 11/11 checks de integridad superados.
- Colección `upme.municipalities`: 170 documentos, `is_pdet: true` en todos.
- Índices activos: `geometry_2dsphere`, `divipola_1` (único), `is_pdet_1`.
- Área total PDET: **389,182 km²** ≈ 34% del territorio nacional (consistente con cifras ART).
- Prueba `$geoIntersects`: Tumaco → 1 hit ✅ | Bogotá D.C. → 0 hits ✅

---

### Semana 3 — Carga de Huellas de Edificios (próxima)

**Objetivo:** Cargar los datasets de Microsoft y Google para los municipios PDET.

Scripts preparados en `compartido/scripts/`:
- `download_buildings.py` — Descarga tiles MS y Google para el bbox PDET.
- `load_buildings.py` — Carga en `buildings_ms` / `buildings_google`, ejecuta join espacial, precomputa áreas.
- `eda_buildings.py` — Análisis exploratorio inicial (conteos, distribución de áreas, cobertura por municipio).

---

### Semanas 4 y 5 — Análisis y Reporte Final (pendiente)

- Workflow reproducible de análisis geoespacial.
- Mapas coropléticos de potencial solar por municipio.
- Comparación MS vs Google: conteos, áreas, cobertura.
- Reporte técnico final con recomendaciones para UPME.

---

## 4. Reproducibilidad

El pipeline completo se reproduce desde un checkout limpio con:

```bash
# Infraestructura
docker compose up -d
docker compose exec mongo mongosh -u root -p root \
  --authenticationDatabase admin /semana_1/init.js

# Semana 2: datos PDET
# (colocar data/raw/municipios_colombia.geojson según compartido/data/raw/SOURCES.md)
python semana_2/validate_pdet.py
python semana_2/load_municipalities.py

# Opcional: verificar validador y generar mapa
docker compose exec mongo mongosh -u root -p root \
  --authenticationDatabase admin /semana_2/verify_schema_validator.js
python semana_2/generate_map.py
```

Todas las operaciones de carga son **idempotentes** (upsert por DIVIPOLA),
el log de validación se autogenera en cada ejecución, y los archivos grandes
no se incluyen en el repositorio pero tienen instrucciones de reproducción
detalladas en `compartido/data/raw/SOURCES.md`.

---

## 5. Archivos grandes (no incluidos)

| Archivo | Tamaño | Cómo regenerar |
|---|---|---|
| `data/raw/municipios_colombia.geojson` | ~273 MB | Ver `compartido/data/raw/SOURCES.md` → sección MGN 2025 |
| `data/processed/pdet_municipios.geojson` | ~65 MB | `python semana_2/validate_pdet.py` |
| `data/raw/ms_buildings/*.csv.gz` | ~650 MB | `python compartido/scripts/download_buildings.py --ms` |
| `data/raw/google_buildings/*_buildings.csv.gz` | ~2.9 GB | `python compartido/scripts/download_buildings.py --google` |

---

## 6. Estructura del Repositorio

```
proyecto/
├── RESUMEN_EJECUTIVO.md          ← Este documento
├── README.md                     ← Inicio rápido y roadmap
│
├── semana_1/                     ← Entrega Semana 1
│   ├── data-model.md             Diseño del modelo NoSQL
│   ├── init.js                   Crea colecciones, validadores e índices
│   └── smoke_load.js             Prueba end-to-end con datos sintéticos
│
├── semana_2/                     ← Entrega Semana 2
│   ├── informe_semana2.md/pdf    Informe completo
│   ├── metodologia_carga_pdet.md Metodología detallada
│   ├── validacion_datos.md       Log de los 11 checks (autogenerado)
│   ├── notas_defensa.md          Contenido para la presentación
│   ├── validate_pdet.py          Validación y emisión del GeoJSON limpio
│   ├── load_municipalities.py    Carga en MongoDB (idempotente)
│   ├── verify_schema_validator.js Demuestra el validador activo
│   ├── generate_map.py           Genera mapa PNG por subregión
│   └── screenshots/              Evidencias de MongoDB y queries
│
└── compartido/                   ← Infraestructura compartida
    ├── docker-compose.yml        MongoDB 7 + Mongo Express
    ├── schema/                   Contratos JSON Schema (3 colecciones)
    ├── scripts/                  Scripts Semana 3+ (download, load, EDA)
    └── data/
        ├── raw/                  Fuentes pequeñas committeadas + SOURCES.md
        └── processed/            Outputs generados (no committeados, ver .gitkeep)
```
