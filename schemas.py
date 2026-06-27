"""
Data models — request/response schemas and internal state.
"""

from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional
from datetime import datetime
import uuid


# ── Enums ─────────────────────────────────────────────────────────────────────

class RideStatus(str, Enum):
    SEARCHING   = "searching"    # looking for driver
    ACCEPTED    = "accepted"     # driver accepted
    EN_ROUTE    = "en_route"     # driver heading to pickup
    ARRIVED     = "arrived"      # driver at pickup
    IN_PROGRESS = "in_progress"  # passenger in vehicle
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"


class DriverStatus(str, Enum):
    AVAILABLE = "available"
    BUSY      = "busy"
    OFFLINE   = "offline"


class RideType(str, Enum):
    ECONOMY = "economy"
    COMFORT = "comfort"
    SUV     = "suv"


# ── Location ──────────────────────────────────────────────────────────────────

class LatLng(BaseModel):
    lat: float = Field(..., ge=-90,  le=90,  description="Latitude")
    lng: float = Field(..., ge=-180, le=180, description="Longitude")
    name: Optional[str] = None


# ── Driver ────────────────────────────────────────────────────────────────────

class DriverInfo(BaseModel):
    id:          str
    name:        str
    plate:       str
    vehicle:     str
    rating:      float
    status:      DriverStatus
    location:    LatLng
    eta_seconds: Optional[int] = None    # ETA to pickup
    ride_type:   RideType = RideType.ECONOMY


class NearbyDriversRequest(BaseModel):
    pickup:    LatLng
    ride_type: RideType = RideType.ECONOMY
    radius_km: float = 5.0


# ── Fare ──────────────────────────────────────────────────────────────────────

class FareEstimate(BaseModel):
    ride_type:    RideType
    distance_km:  float
    duration_min: int
    base_fare:    int       # NPR
    per_km_rate:  int       # NPR/km
    total_fare:   int       # NPR


class FareRequest(BaseModel):
    pickup:    LatLng
    dropoff:   LatLng
    ride_type: RideType = RideType.ECONOMY


# ── Ride ──────────────────────────────────────────────────────────────────────

class BookRideRequest(BaseModel):
    passenger_id: str
    pickup:       LatLng
    dropoff:      LatLng
    ride_type:    RideType = RideType.ECONOMY
    driver_id:    Optional[str] = None   # optional: request specific driver


class RideResponse(BaseModel):
    ride_id:      str
    status:       RideStatus
    driver:       Optional[DriverInfo]
    fare:         FareEstimate
    pickup:       LatLng
    dropoff:      LatLng
    created_at:   datetime
    accepted_at:  Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ── WebSocket messages ─────────────────────────────────────────────────────────

class WSMessageType(str, Enum):
    LOCATION_UPDATE  = "location_update"
    RIDE_STATUS      = "ride_status"
    DRIVER_ASSIGNED  = "driver_assigned"
    ETA_UPDATE       = "eta_update"
    MESSAGE          = "message"
    ERROR            = "error"


class LocationUpdate(BaseModel):
    driver_id:  str
    ride_id:    Optional[str]
    location:   LatLng
    heading:    float = 0.0     # degrees 0-360
    speed_kmh:  float = 0.0
    timestamp:  datetime = Field(default_factory=datetime.utcnow)


class WSMessage(BaseModel):
    type:      WSMessageType
    ride_id:   Optional[str] = None
    data:      dict
    timestamp: datetime = Field(default_factory=datetime.utcnow)
