/**
 * Week 2 — Verificación del $jsonSchema validator en upme.municipalities
 *
 * Demuestra que el validator activo rechaza documentos malformados,
 * lo cual es evidencia directa de que init.js instaló el schema correctamente.
 *
 * Uso:
 *   docker compose exec mongo mongosh -u root -p root \
 *     --authenticationDatabase admin /scripts/verify_schema_validator.js
 */

const db = connect("mongodb://root:root@localhost:27017/upme?authSource=admin");
const coll = db.municipalities;

print("\n========== Schema Validator Verification ==========\n");

// 1. Mostrar info de la colección (incluye validador activo)
const info = db.getCollectionInfos({ name: "municipalities" });
if (info.length === 0) {
  print("[FAIL] Colección 'municipalities' no existe. Ejecuta init.js primero.");
  quit(1);
}
const options = info[0].options || {};
const hasValidator = !!options.validator;
print(`[${hasValidator ? "OK" : "FAIL"}] $jsonSchema validator instalado: ${hasValidator}`);
print(`       validationLevel:  ${options.validationLevel  || "N/A"}`);
print(`       validationAction: ${options.validationAction || "N/A"}`);

// 2. Intentar insertar un documento malformado (falta 'divipola')
print("\n[*] Intentando insertar documento malformado (sin 'divipola')...");
let rejected = false;
try {
  coll.insertOne({
    name: "MUNICIPIO_FALSO",
    department: "TEST",
    is_pdet: true,
    area_sqkm: 100,
    geometry: { type: "Point", coordinates: [0, 0] },
  });
  print("[FAIL] El validator NO rechazó el documento malformado.");
} catch (e) {
  rejected = true;
  print(`[OK]   Documento rechazado correctamente.`);
  print(`       Error: ${e.message.slice(0, 120)}...`);
}

// 3. Intentar insertar un documento válido mínimo (solo para probar; lo borramos)
print("\n[*] Insertando documento válido de prueba...");
const testDivipola = "00000";
try {
  coll.insertOne({
    divipola: testDivipola,
    name: "TEST_MUNI",
    department: "TEST_DEPT",
    department_code: "00",
    is_pdet: true,
    area_sqkm: 1.0,
    subregion_pdet: "TEST_SUBREGION",
    source: "test",
    loaded_at: new Date().toISOString(),
    geometry: {
      type: "MultiPolygon",
      coordinates: [[[[0,0],[1,0],[1,1],[0,1],[0,0]]]],
    },
  });
  print("[OK]   Documento válido insertado.");
  coll.deleteOne({ divipola: testDivipola });
  print("[OK]   Documento de prueba eliminado.");
} catch (e) {
  print(`[FAIL] Documento válido rechazado: ${e.message.slice(0, 200)}`);
}

// 4. Resumen de índices
print("\n[*] Índices activos:");
coll.getIndexes().forEach(idx => print(`       ${idx.name}`));

print("\n========== Fin de verificación ==========\n");
