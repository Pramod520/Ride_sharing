"""
Routing service — wraps the OSRM public API.

Uses the free public OSRM demo server (router.project-osrm.org).
In production, self-host OSRM with Nepal PBF data:
  docker run -t -v $(pwd):/data osrm/osrm-backend osrm-extract \
    -p /opt/car.lua /data/nepal-latest.osm.pbf

OSRM docs: https://project-osrm.org/docs/v5.5.1/api/
"""

import httpx
import math
from typing import List, Tuple, Optional
from app.models.schemas import LatLng, FareEstimate, RideType

OSRM_BASE = "https://router.project-osrm.org/route/v1/driving"

# NPR fare config per ride type
FARE_CONFIG = {
    RideType.ECONOMY: {"base": 50,  "per_km": 85},
    RideType.COMFORT: {"base": 70,  "per_km": 119},
    RideType.SUV:     {"base": 90,  "per_km": 162},
}


async def get_route(
    pickup: LatLng,
    dropoff: LatLng,
) -> Tuple[List[List[float]], float, int]:
    """
    Fetch route from OSRM.

    Returns:
        coords      — list of [lat, lng] waypoints along the road
        distance_km — total route distance
        duration_s  — estimated driving time in seconds
    """
    url = (
        f"{OSRM_BASE}/{pickup.lng},{pickup.lat};"
        f"{dropoff.lng},{dropoff.lat}"
        f"?overview=full&geometries=geojson&steps=false"
    )

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            route = data["routes"][0]
            coords = [
                [c[1], c[0]]   # OSRM returns [lng, lat] — flip to [lat, lng]
                for c in route["geometry"]["coordinates"]
            ]
            distance_km = route["distance"] / 1000
            duration_s  = int(route["duration"])
            return coords, round(distance_km, 2), duration_s
        except Exception:
            # Fallback: straight line with estimated values
            dist = haversine(pickup.lat, pickup.lng, dropoff.lat, dropoff.lng)
            return (
                [[pickup.lat, pickup.lng], [dropoff.lat, dropoff.lng]],
                round(dist, 2),
                int(dist / 30 * 3600),
            )


def calculate_fare(distance_km: float, duration_s: int, ride_type: RideType) -> FareEstimate:
    cfg  = FARE_CONFIG[ride_type]
    base = cfg["base"]
    rate = cfg["per_km"]
    total = int(base + distance_km * rate)
    return FareEstimate(
        ride_type    = ride_type,
        distance_km  = round(distance_km, 2),
        duration_min = max(1, round(duration_s / 60)),
        base_fare    = base,
        per_km_rate  = rate,
        total_fare   = total,
    )


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2)**2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlng/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def interpolate_path(coords: List[List[float]], step: int, total_steps: int) -> Optional[List[float]]:
    """Get interpolated position along a route for smooth animation."""
    if not coords or total_steps <= 0:
        return None
    idx = min(int((step / total_steps) * (len(coords) - 1)), len(coords) - 1)
    return coords[idx]
