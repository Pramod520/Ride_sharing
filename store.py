"""
In-memory state store.
Replace with Redis + PostGIS in production.
"""

from typing import Dict, List, Optional
from app.models.schemas import DriverInfo, DriverStatus, RideResponse, RideStatus, LatLng, RideType
from datetime import datetime
import uuid
import math


# ── Seed drivers with real Kathmandu coordinates ──────────────────────────────

SEED_DRIVERS: List[DriverInfo] = [
    DriverInfo(id="d1", name="Ram Kumar",     plate="BA 1 PA 2345", vehicle="Hyundai i20",
               rating=4.9, status=DriverStatus.AVAILABLE,
               location=LatLng(lat=27.7210, lng=85.3080, name="Maharajgunj"),
               ride_type=RideType.ECONOMY),

    DriverInfo(id="d2", name="Sita Paudel",   plate="BA 2 KA 5678", vehicle="Suzuki Swift",
               rating=4.7, status=DriverStatus.AVAILABLE,
               location=LatLng(lat=27.7080, lng=85.3200, name="Lazimpat"),
               ride_type=RideType.COMFORT),

    DriverInfo(id="d3", name="Bikash Tamang", plate="BA 3 CHA 9012", vehicle="Toyota Vitz",
               rating=4.8, status=DriverStatus.AVAILABLE,
               location=LatLng(lat=27.7300, lng=85.3350, name="Chabahil"),
               ride_type=RideType.ECONOMY),

    DriverInfo(id="d4", name="Gita Rai",      plate="BA 4 JA 3456", vehicle="Mahindra Bolero",
               rating=4.6, status=DriverStatus.AVAILABLE,
               location=LatLng(lat=27.6950, lng=85.3450, name="Koteshwor"),
               ride_type=RideType.SUV),

    DriverInfo(id="d5", name="Rohan Shrestha",plate="BA 5 NA 7890", vehicle="Honda City",
               rating=4.9, status=DriverStatus.BUSY,
               location=LatLng(lat=27.7150, lng=85.2950, name="Swayambhu"),
               ride_type=RideType.COMFORT),
]


class Store:
    def __init__(self):
        self.drivers: Dict[str, DriverInfo] = {d.id: d for d in SEED_DRIVERS}
        self.rides:   Dict[str, RideResponse] = {}

    # ── Drivers ──────────────────────────────────────────────────────────────

    def get_driver(self, driver_id: str) -> Optional[DriverInfo]:
        return self.drivers.get(driver_id)

    def all_drivers(self) -> List[DriverInfo]:
        return list(self.drivers.values())

    def update_driver_location(self, driver_id: str, lat: float, lng: float):
        if driver_id in self.drivers:
            self.drivers[driver_id].location.lat = lat
            self.drivers[driver_id].location.lng = lng

    def set_driver_status(self, driver_id: str, status: DriverStatus):
        if driver_id in self.drivers:
            self.drivers[driver_id].status = status

    def nearest_available_drivers(
        self, lat: float, lng: float,
        ride_type: Optional[RideType] = None,
        limit: int = 5,
        radius_km: float = 10.0,
    ) -> List[DriverInfo]:
        candidates = []
        for d in self.drivers.values():
            if d.status != DriverStatus.AVAILABLE:
                continue
            if ride_type and d.ride_type != ride_type:
                continue
            dist = haversine(lat, lng, d.location.lat, d.location.lng)
            if dist <= radius_km:
                d.eta_seconds = int(dist / 30 * 3600)   # ~30 km/h city speed
                candidates.append((dist, d))
        candidates.sort(key=lambda x: x[0])
        return [d for _, d in candidates[:limit]]

    # ── Rides ─────────────────────────────────────────────────────────────────

    def create_ride(self, ride: RideResponse) -> RideResponse:
        self.rides[ride.ride_id] = ride
        return ride

    def get_ride(self, ride_id: str) -> Optional[RideResponse]:
        return self.rides.get(ride_id)

    def update_ride_status(self, ride_id: str, status: RideStatus) -> Optional[RideResponse]:
        if ride_id in self.rides:
            self.rides[ride_id].status = status
            if status == RideStatus.COMPLETED:
                self.rides[ride_id].completed_at = datetime.utcnow()
            return self.rides[ride_id]
        return None


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance between two points in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


# Global singleton
store = Store()
