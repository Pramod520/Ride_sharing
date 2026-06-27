"""
Drivers API
-----------
GET  /api/drivers                         — list all drivers
GET  /api/drivers/{driver_id}             — driver detail
POST /api/drivers/{driver_id}/location    — real driver app posts GPS here
PUT  /api/drivers/{driver_id}/status      — go online/offline
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime

from app.models.schemas import DriverInfo, DriverStatus, LocationUpdate
from app.services.store import store
from app.services.connection_manager import manager

router = APIRouter()


class LocationPayload(BaseModel):
    lat: float
    lng: float
    heading: float = 0.0
    speed_kmh: float = 0.0


class StatusPayload(BaseModel):
    status: DriverStatus


@router.get("/", summary="List all drivers")
async def list_drivers():
    return {"drivers": [d.model_dump() for d in store.all_drivers()]}


@router.get("/{driver_id}", response_model=DriverInfo, summary="Driver detail")
async def get_driver(driver_id: str):
    d = store.get_driver(driver_id)
    if not d:
        raise HTTPException(404, f"Driver {driver_id} not found")
    return d


@router.post("/{driver_id}/location", summary="Update driver GPS location")
async def update_location(driver_id: str, payload: LocationPayload):
    """
    Real driver mobile app calls this endpoint every ~1s with GPS coordinates.
    Server updates store + broadcasts via WebSocket to passenger.
    """
    d = store.get_driver(driver_id)
    if not d:
        raise HTTPException(404, f"Driver {driver_id} not found")

    store.update_driver_location(driver_id, payload.lat, payload.lng)

    update_msg = {
        "type":      "location_update",
        "driver_id": driver_id,
        "location":  {"lat": round(payload.lat, 6), "lng": round(payload.lng, 6)},
        "heading":   payload.heading,
        "speed_kmh": payload.speed_kmh,
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Broadcast to passenger tracking this driver's active ride
    for ride in store.rides.values():
        if (ride.driver and ride.driver.id == driver_id
                and ride.status not in ("completed", "cancelled")):
            await manager.broadcast_to_ride(ride.ride_id, update_msg)
            break

    # Always broadcast to dispatchers
    await manager.broadcast_to_dispatchers(update_msg)

    return {"ok": True}


@router.put("/{driver_id}/status", summary="Set driver status (online/offline)")
async def set_status(driver_id: str, payload: StatusPayload):
    d = store.get_driver(driver_id)
    if not d:
        raise HTTPException(404, f"Driver {driver_id} not found")
    store.set_driver_status(driver_id, payload.status)
    await manager.broadcast_to_dispatchers({
        "type":      "driver_status",
        "driver_id": driver_id,
        "status":    payload.status,
        "timestamp": datetime.utcnow().isoformat(),
    })
    return {"driver_id": driver_id, "status": payload.status}
