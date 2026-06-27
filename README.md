# NepRide — Real-time Dispatcher Backend

FastAPI + WebSocket backend for the Nepal ride-hailing app.
Pairs with the Leaflet.js frontend built in the previous step.

---

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 3. Open interactive API docs
open http://localhost:8000/docs
```

---

## Architecture

```
Passenger App (Leaflet.js)
    │
    ├── POST /api/rides/fare          ← estimate fare (OSRM routing)
    ├── POST /api/rides/nearby-drivers ← find nearest driver
    ├── POST /api/rides/book          ← book ride, get ride_id
    └── WS  /ws/passenger/{ride_id}  ← live GPS stream
            │
            │  broadcasts every 1s:
            │  { type: "location_update", location: {lat, lng}, eta_seconds, progress_pct }
            │  { type: "ride_status",     status: "en_route" | "arrived" | "in_progress" | "completed" }
            │
Driver App (Mobile)
    ├── WS  /ws/driver/{driver_id}   ← sends GPS, receives assignments
    └── POST /api/drivers/{id}/location ← REST alternative for GPS updates

Dispatcher Dashboard
    └── WS  /ws/dispatcher           ← all driver positions + ride events
```

---

## WebSocket message reference

### Passenger receives

```json
// Driver moving toward you
{ "type": "location_update",
  "driver_id": "d1",
  "location": { "lat": 27.7154, "lng": 85.3123 },
  "eta_seconds": 142,
  "progress_pct": 34 }

// Status change
{ "type": "ride_status",
  "status": "en_route" | "arrived" | "in_progress" | "completed",
  "message": "Ram Kumar is on the way to you" }
```

### Driver sends (via WS)

```json
{ "type": "location", "lat": 27.7154, "lng": 85.3123, "heading": 45.0, "speed_kmh": 28 }
{ "type": "status",   "status": "available" | "busy" | "offline" }
```

---

## Connecting the Leaflet.js frontend

Replace the mock `startLiveTracking()` function in the frontend with:

```javascript
async function bookRide() {
  // 1. Book the ride via REST
  const res = await fetch('http://localhost:8000/api/rides/book', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      passenger_id: 'user-123',
      pickup:  { lat: pickLat,  lng: pickLng,  name: pickName },
      dropoff: { lat: dropLat,  lng: dropLng,  name: dropName },
      ride_type: 'economy',
    })
  });
  const ride = await res.json();

  // 2. Open WebSocket for live tracking
  const ws = new WebSocket(`ws://localhost:8000/ws/passenger/${ride.ride_id}`);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    if (msg.type === 'location_update') {
      // Move driver marker on Leaflet map
      driverMarker.setLatLng([msg.location.lat, msg.location.lng]);
      updateETA(msg.eta_seconds);
      updateProgress(msg.progress_pct);
    }

    if (msg.type === 'ride_status') {
      updateStatusBanner(msg.status, msg.message);
      if (msg.status === 'completed') ws.close();
    }
  };
}
```

---

## Production upgrades

| Component | Dev (current) | Production |
|-----------|--------------|------------|
| State store | In-memory dict | Redis + PostGIS (PostgreSQL) |
| Driver GPS simulator | Background asyncio task | Real driver mobile app |
| OSRM routing | Public demo server | Self-hosted OSRM with Nepal PBF |
| Auth | None | JWT tokens (FastAPI-Users) |
| Deployment | uvicorn | Docker + Nginx + Gunicorn |

### Self-host OSRM with Nepal data

```bash
# Download Nepal OSM data
wget https://download.geofabrik.de/asia/nepal-latest.osm.pbf

# Run OSRM via Docker
docker run -t -v $(pwd):/data osrm/osrm-backend \
  osrm-extract -p /opt/car.lua /data/nepal-latest.osm.pbf
docker run -t -v $(pwd):/data osrm/osrm-backend osrm-partition /data/nepal-latest.osrm
docker run -t -v $(pwd):/data osrm/osrm-backend osrm-customize /data/nepal-latest.osrm
docker run -t -p 5000:5000 -v $(pwd):/data osrm/osrm-backend \
  osrm-routed --algorithm mld /data/nepal-latest.osrm

# Then update routing.py:
OSRM_BASE = "http://localhost:5000/route/v1/driving"
```

### PostGIS driver location query

```sql
-- Find drivers within 5km of a point using PostGIS
SELECT driver_id, name, plate,
       ST_Distance(
         location::geography,
         ST_MakePoint(85.3123, 27.7154)::geography
       ) / 1000 AS distance_km
FROM drivers
WHERE status = 'available'
  AND ST_DWithin(
        location::geography,
        ST_MakePoint(85.3123, 27.7154)::geography,
        5000   -- metres
      )
ORDER BY distance_km
LIMIT 5;
```
