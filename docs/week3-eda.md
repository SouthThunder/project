# Week 3 — Initial Data Audit (EDA)

Generated: 2026-05-24T02:35:59+00:00

## 1. Totals

| Source | Documents | Tagged to PDET | Total rooftop area (km²) | Mean area (m²) |
| --- | ---: | ---: | ---: | ---: |
| Microsoft | 1,763,356 | 1,763,356 | 221.18 | 125.43 |
| Google | 2,691,812 | 2,691,812 | 222.90 | 82.81 |

## 2. Top 15 PDET municipalities by Microsoft rooftop area

| DIVIPOLA | Name | Department | MS buildings | MS rooftop km² | Google buildings | Google rooftop km² |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 47001 | SANTA MARTA | MAGDALENA | 67,435 | 14.18 | 183,114 | 16.00 |
| 20001 | VALLEDUPAR | CESAR | 64,088 | 13.53 | 171,908 | 15.41 |
| 76109 | BUENAVENTURA | VALLE DEL CAUCA | 34,382 | 7.27 | 104,324 | 7.70 |
| 18001 | FLORENCIA | CAQUETÁ | 26,757 | 6.67 | 57,994 | 7.35 |
| 05837 | TURBO | ANTIOQUIA | 42,642 | 4.59 | 77,890 | 5.96 |
| 52835 | SAN ANDRES DE TUMACO | NARIÑO | 41,294 | 4.51 | 49,702 | 3.71 |
| 19698 | SANTANDER DE QUILICHAO | CAUCA | 30,873 | 4.24 | 35,527 | 3.85 |
| 54810 | TIBÚ | NORTE DE SANTANDER | 35,339 | 3.55 | 32,767 | 2.65 |
| 18753 | SAN VICENTE DEL CAGUÁN | CAQUETÁ | 22,363 | 3.54 | 22,232 | 2.67 |
| 81065 | ARAUQUITA | ARAUCA | 29,059 | 3.46 | 36,164 | 3.02 |
| 05045 | APARTADÓ | ANTIOQUIA | 10,304 | 3.45 | 37,193 | 3.70 |
| 19256 | EL TAMBO | CAUCA | 37,012 | 3.29 | 43,200 | 2.71 |
| 95001 | SAN JOSÉ DEL GUAVIARE | GUAVIARE | 21,535 | 3.11 | 32,798 | 3.17 |
| 81736 | SARAVENA | ARAUCA | 17,499 | 3.08 | 27,625 | 2.19 |
| 86568 | PUERTO ASÍS | PUTUMAYO | 20,266 | 2.96 | 26,218 | 2.56 |

## 3. Cross-source coverage delta

Number of PDET munis each source has > 0 detections for, plus a count of munis where the building-count differs by > 20 %.

- Munis with MS detections: **169** / 170
- Munis with Google detections: **165** / 170
- Munis with both: **165**
- MS only: **4**
- Google only: **0**
- Munis where MS and Google counts differ by > 20 %: **126**

## 4. Google confidence distribution

| Bucket | Count |
| --- | ---: |
| 0.6 | 429,902 |
| 0.7 | 1,142,547 |
| 0.8 | 1,042,360 |
| 0.9 | 77,003 |

## 5. Building area distribution (m²)

| Source | p10 | p50 | p90 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| Microsoft | 28.85 | 76.99 | 229.46 | 908.33 | 44,667.04 |
| Google | 16.72 | 58.05 | 160.30 | 447.13 | 42,207.13 |
