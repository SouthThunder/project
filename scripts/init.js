// Week 1 deliverable: create the upme database, collections, $jsonSchema
// validators, and indexes. Idempotent - safe to re-run.
//
// Run inside the container:
//   docker compose exec mongo mongosh -u root -p root \
//     --authenticationDatabase admin /scripts/init.js

const dbName = "upme";
const db_ = db.getSiblingDB(dbName);

const fs = require("fs");
function loadSchema(path) {
  return JSON.parse(fs.readFileSync(path, "utf8"));
}

function ensureCollection(name, jsonSchema) {
  const exists = db_.getCollectionNames().includes(name);
  const validator = { $jsonSchema: jsonSchema };
  if (!exists) {
    db_.createCollection(name, {
      validator,
      validationLevel: "moderate",
      validationAction: "error",
    });
    print(`[+] created collection ${name}`);
  } else {
    db_.runCommand({ collMod: name, validator, validationLevel: "moderate", validationAction: "error" });
    print(`[=] updated validator on ${name}`);
  }
}

function ensureIndex(coll, keys, opts) {
  db_[coll].createIndex(keys, opts || {});
  print(`[+] index on ${coll}: ${JSON.stringify(keys)} ${opts ? JSON.stringify(opts) : ""}`);
}

// ---- Schemas ----
// $jsonSchema in MongoDB is a *subset* of JSON Schema and rejects keywords
// like $schema, $id, additionalProperties:false-with-_id, format, etc. We
// therefore strip the parts Mongo cannot evaluate before installing the
// validator. The full schema files in /schema remain the source of truth
// for documentation and external tooling.
function mongoize(schema) {
  const clone = JSON.parse(JSON.stringify(schema));
  delete clone.$schema; delete clone.$id; delete clone.title; delete clone.description;
  // Mongo's $jsonSchema does not accept "format"; strip recursively.
  (function walk(node) {
    if (!node || typeof node !== "object") return;
    delete node.format;
    // $jsonSchema doesn't support "type":"integer" - translate to bsonType.
    if (node.type === "integer") { delete node.type; node.bsonType = ["int", "long"]; }
    if (Array.isArray(node.type) && node.type.includes("integer")) {
      node.type = node.type.filter(t => t !== "integer");
      if (node.type.length === 1) node.type = node.type[0];
    }
    for (const k of Object.keys(node)) walk(node[k]);
  })(clone);
  return clone;
}

const muniSchema      = mongoize(loadSchema("/schema/municipalities.schema.json"));
const buildingsSchema = mongoize(loadSchema("/schema/buildings.schema.json"));
const resultsSchema   = mongoize(loadSchema("/schema/results.schema.json"));

// ---- Collections ----
ensureCollection("municipalities",   muniSchema);
ensureCollection("buildings_ms",     buildingsSchema);
ensureCollection("buildings_google", buildingsSchema);
ensureCollection("results",          resultsSchema);

// ---- Indexes ----
// municipalities: spatial index for the building->muni join, plus unique on DIVIPOLA.
ensureIndex("municipalities", { geometry: "2dsphere" });
ensureIndex("municipalities", { divipola: 1 }, { unique: true });
ensureIndex("municipalities", { is_pdet: 1 });

// buildings_*: spatial index for $geoWithin queries, divipola for grouping,
// confidence for filtering Google's noisier detections.
for (const c of ["buildings_ms", "buildings_google"]) {
  ensureIndex(c, { geometry: "2dsphere" });
  ensureIndex(c, { divipola: 1 });
  ensureIndex(c, { source: 1, divipola: 1 });
  ensureIndex(c, { confidence: 1 }, { sparse: true });
}

// results: one row per (muni, source) - the analysis output.
ensureIndex("results", { divipola: 1, source: 1 }, { unique: true });

print("\n[OK] init.js complete. Collections:");
printjson(db_.getCollectionNames());
