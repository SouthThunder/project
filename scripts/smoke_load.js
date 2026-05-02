// Week 1 smoke test: prove the schema works end-to-end with synthetic data.
// Real DANE/MS/Google loaders are week 2-3 deliverables.
//
// What this does:
//   1. Inserts ONE synthetic PDET municipality polygon (a ~5km square near
//      Tumaco, Nariño - DIVIPOLA 52835).
//   2. Generates ~800 fake Microsoft buildings + ~600 fake Google buildings
//      uniformly inside the polygon.
//   3. Tags every building with its containing municipality via $geoIntersects
//      (this is the spatial-join ETL pattern week 3 will run on real data).
//   4. Aggregates building_count / total_rooftop_sqm per (divipola, source)
//      and writes to the results collection.
//   5. Prints a side-by-side comparison so you can screenshot it.
//
// Idempotent. Run with:
//   docker compose exec mongo mongosh -u root -p root \
//     --authenticationDatabase admin /scripts/smoke_load.js

const db_ = db.getSiblingDB("upme");

// ---------- 1. Municipality ----------
// Synthetic 5km x 5km square around Tumaco's town center. Real polygons come
// from the DANE MGN ZIP in week 2.
const lat0 = 1.79, lon0 = -78.78;
const dLat = 0.0225;   // ~2.5 km north
const dLon = 0.0225;   // ~2.5 km east (close enough at this latitude for a smoke test)

const muniPolygon = {
  type: "Polygon",
  coordinates: [[
    [lon0 - dLon, lat0 - dLat],
    [lon0 + dLon, lat0 - dLat],
    [lon0 + dLon, lat0 + dLat],
    [lon0 - dLon, lat0 + dLat],
    [lon0 - dLon, lat0 - dLat],
  ]],
};

db_.municipalities.replaceOne(
  { divipola: "52835" },
  {
    divipola: "52835",
    name: "Tumaco",
    department: "Nariño",
    department_code: "52",
    is_pdet: true,
    area_sqkm: 25.0,
    source: "SYNTHETIC (week-1 smoke test)",
    loaded_at: new Date().toISOString(),
    geometry: muniPolygon,
  },
  { upsert: true },
);
print("[+] inserted/updated municipality 52835 Tumaco (synthetic)");

// ---------- 2. Synthetic buildings ----------
function randomBuildingPolygon() {
  // Random center within the muni polygon, then a small ~10m square footprint.
  const cx = lon0 + (Math.random() * 2 - 1) * dLon * 0.95;
  const cy = lat0 + (Math.random() * 2 - 1) * dLat * 0.95;
  // ~10 meters in degrees: 1 deg lat ~ 111 km, so 10 m ~ 0.00009 deg.
  const halfSide = 0.00005 + Math.random() * 0.0001;
  return {
    polygon: {
      type: "Polygon",
      coordinates: [[
        [cx - halfSide, cy - halfSide],
        [cx + halfSide, cy - halfSide],
        [cx + halfSide, cy + halfSide],
        [cx - halfSide, cy + halfSide],
        [cx - halfSide, cy - halfSide],
      ]],
    },
    // Approximate area for a tiny equirectangular square at this latitude.
    area_sqm: Math.pow(halfSide * 2 * 111_320 * Math.cos(cy * Math.PI / 180), 2),
  };
}

function loadSynthetic(coll, source, n) {
  db_[coll].deleteMany({ source: source, source_id: { $regex: "^synthetic-" } });
  const batch = [];
  for (let i = 0; i < n; i++) {
    const b = randomBuildingPolygon();
    batch.push({
      source: source,
      source_id: `synthetic-${i}`,
      divipola: null,                 // populated by the spatial-join below
      confidence: source === "google" ? 0.7 + Math.random() * 0.3 : null,
      area_sqm: b.area_sqm,
      loaded_at: new Date().toISOString(),
      geometry: b.polygon,
    });
  }
  const r = db_[coll].insertMany(batch, { ordered: false });
  print(`[+] inserted ${Object.keys(r.insertedIds).length} synthetic ${source} buildings into ${coll}`);
}

loadSynthetic("buildings_ms",     "microsoft", 800);
loadSynthetic("buildings_google", "google",    600);

// ---------- 3. Spatial-join ETL: tag buildings with containing PDET muni ----------
// This is the pattern the real ETL will use in week 3. Doing it once at load
// time (instead of on every analytical query) trades write cost for read cost
// - the right call when reads vastly outnumber writes, which they do here.
function tagBuildings(coll) {
  let tagged = 0;
  db_.municipalities.find({ is_pdet: true }).forEach(function (muni) {
    const r = db_[coll].updateMany(
      { geometry: { $geoWithin: { $geometry: muni.geometry } } },
      { $set: { divipola: muni.divipola } },
    );
    tagged += r.modifiedCount;
  });
  print(`[+] tagged ${tagged} ${coll} buildings with their PDET divipola`);
}
tagBuildings("buildings_ms");
tagBuildings("buildings_google");

// ---------- 4. Aggregate into results ----------
function aggregate(coll, sourceLabel) {
  const pipeline = [
    { $match: { divipola: { $ne: null } } },
    { $group: {
      _id: { divipola: "$divipola", source: "$source" },
      building_count: { $sum: 1 },
      total_rooftop_sqm: { $sum: "$area_sqm" },
      mean_area_sqm: { $avg: "$area_sqm" },
    } },
    { $lookup: {
      from: "municipalities",
      localField: "_id.divipola",
      foreignField: "divipola",
      as: "muni",
    } },
    { $unwind: "$muni" },
    { $project: {
      _id: 0,
      divipola:          "$_id.divipola",
      source:            "$_id.source",
      name:              "$muni.name",
      department:        "$muni.department",
      building_count:    1,
      total_rooftop_sqm: { $round: ["$total_rooftop_sqm", 2] },
      mean_area_sqm:     { $round: ["$mean_area_sqm",     2] },
      computed_at:       { $literal: new Date().toISOString() },
    } },
  ];
  const rows = db_[coll].aggregate(pipeline).toArray();
  rows.forEach(function (row) {
    db_.results.replaceOne(
      { divipola: row.divipola, source: row.source },
      row,
      { upsert: true },
    );
  });
  print(`[+] wrote ${rows.length} result rows for ${sourceLabel}`);
}
aggregate("buildings_ms",     "microsoft");
aggregate("buildings_google", "google");

// ---------- 5. Side-by-side comparison ----------
print("\n=== Per-municipality, per-source results (smoke test) ===");
const summary = db_.results.aggregate([
  { $sort: { divipola: 1, source: 1 } },
]).toArray();
printjson(summary);

print("\n=== Cross-source comparison ===");
const comparison = db_.results.aggregate([
  { $group: {
    _id: "$divipola",
    name: { $first: "$name" },
    by_source: { $push: { source: "$source", count: "$building_count", total_sqm: "$total_rooftop_sqm" } },
  } },
]).toArray();
printjson(comparison);
