# Data Sources — Raw Data

## MGN 2025 — Marco Geoestadístico Nacional

| Campo             | Detalle                                                                 |
|-------------------|-------------------------------------------------------------------------|
| **Proveedor**     | DANE — Departamento Administrativo Nacional de Estadística              |
| **Nombre**        | Marco Geoestadístico Nacional (MGN) 2025                               |
| **Versión**       | MGN2025-Colombia, Todos los niveles geográficos                        |
| **URL**           | https://geoportal.dane.gov.co/servicios/descarga-y-metadatos/datos-geoestadisticos/?cod=111 |
| **Fecha descarga**| 2025-05-09                                                              |
| **Formato original** | Shapefile (.shp, .dbf, .shx, .prj)                                 |
| **Tamaño ZIP**    | ~1.5 GB                                                                 |
| **Licencia**      | Uso libre con atribución DANE                                           |

### Archivo utilizado
- **Shapefile:** `ADMINISTRATIVO/MGN_ADM_MPIO_GRAFICO.shp`
- **Convertido a:** `municipios_colombia.geojson` usando QGIS (Export → Save Features As → GeoJSON, CRS: EPSG:4326)
- **Tamaño GeoJSON:** 372 MB

### Descripción
Capa de municipios de Colombia con 1122 registros. Contiene los límites
administrativos oficiales de todos los municipios del país. Se utilizó
para extraer y filtrar los 170 municipios designados como territorios
PDET según el Decreto 893 de 2017.

### Columnas relevantes
| Columna      | Descripción                         |
|--------------|-------------------------------------|
| `mpio_cdpmp` | Código DIVIPOLA del municipio (5 dígitos) |
| `mpio_cnmbr` | Nombre del municipio                |
| `dpto_cnmbr` | Nombre del departamento             |
| `dpto_ccdgo` | Código del departamento (2 dígitos) |
| `mpio_ccdgo` | Código del municipio (3 dígitos)    |
| `geometry`   | Polígono del municipio (WGS84)      |

### Nota
El archivo ZIP original (~1.5 GB) y el shapefile no se incluyen en el repositorio por su tamaño. 
Para reproducir:
1. Descargar el ZIP desde la URL indicada
2. Descomprimir y abrir `MGN_ADM_MPIO_GRAFICO.shp` en QGIS
3. Exportar como GeoJSON (EPSG:4326) a `data/raw/municipios_colombia.geojson`

