"""
Rides API
---------
POST /api/rides/fare          — estimate fare before booking
POST /api/rides/book          — create a ride and assign driver
GET  /api/rides/{ride_id}     — get ride details + status
PUT  /api/rides/{ride_id}/cancel
"""

from fastapi import APIRouter, HTTPException
from datetime import datetime
import uuid

from app.models.schemas import (
    FareRequest, FareEstimate,
    BookRideRequest, RideResponse,
    RideStatus, DriverStatus, NearbyDriversRequest,
)
from app.services.store import store
from app.services.routing import get_route, calculate_fare
from app.services.connection_manager import manager

router = APIRouter()


@router.post("/fare", response_model=FareEstimate, summary="Estimate fare")
async def estimate_fare(req: FareRequest):
    """
    Returns estimated fare for a pickup→dropoff pair using real OSRM routing.
    Distance and duration come from actual Kathmandu road network.
    """
    _, distance_km, duration_s = await get_route(req.pickup, req.dropoff)
    return calculate_fare(distance_km, duration_s, req.ride_type)


@router.post("/nearby-drivers", summary="Find nearest available drivers")
async def nearby_drivers(req: NearbyDriversRequest):
    """
    Returns up to 5 available drivers sorted by distance from pickup,
    with ETA in seconds.
    """
    drivers = store.nearest_available_drivers(
        lat=req.pickup.lat,
        lng=req.pickup.lng,
        ride_type=req.ride_type,
        radius_km=req.radius_km,
    )
    if not drivers:
        # Broaden search if nothing nearby
        drivers = store.nearest_available_drivers(
            lat=req.pickup.lat, lng=req.pickup.lng, radius_km=20.0
        )
    return {"drivers": [d.model_dump() for d in drivers]}


@router.post("/book", response_model=RideResponse, summary="Book a ride")
async def book_ride(req: BookRideRequest):
    """
    Books a ride:
    1. Calculates real route via OSRM
    2. Assigns nearest available driver
    3. Marks driver as BUSY
    4. Returns ride object with full fare details
    5. Notifies driver via WebSocket
    """
    coords, distance_km, duration_s = await get_route(req.pickup, req.dropoff)
    fare = calculate_fare(distance_km, duration_s, req.ride_type)

    # Assign driver
    if req.driver_id:
        driver = store.get_driver(req.driver_id)
        if not driver or driver.status != DriverStatus.AVAILABLE:
            raise HTTPException(400, "Requested driver is not available")
    else:
        candidates = store.nearest_available_drivers(
            lat=req.pickup.lat, lng=req.pickup.lng,
            ride_type=req.ride_type,
        )
        if not candidates:
            raise HTTPException(404, "No drivers available right now. Try again shortly.")
        driver = candidates[0]

    store.set_driver_status(driver.id, DriverStatus.BUSY)

    ride = RideResponse(
        ride_id     = str(uuid.uuid4()),
        status      = RideStatus.ACCEPTED,
        driver      = driver,
        fare        = fare,
        pickup      = req.pickup,
        dropoff     = req.dropoff,
        created_at  = datetime.utcnow(),
        accepted_at = datetime.utcnow(),
    )
    store.create_ride(ride)

    # Notify driver via WebSocket
    await manager.send_to_driver(driver.id, {
        "type":    "ride_assigned",
        "ride_id": ride.ride_id,
        "pickup":  req.pickup.model_dump(),
        "dropoff": req.dropoff.model_dump(),
        "fare":    fare.model_dump(),
    })

    # Notify dispatchers
    await manager.broadcast_to_dispatchers({
        "type":      "ride_booked",
        "ride_id":   ride.ride_id,
        "driver_id": driver.id,
        "pickup":    req.pickup.model_dump(),
        "dropoff":   req.dropoff.model_dump(),
    })

    return ride


@router.get("/{ride_id}", response_model=RideResponse, summary="Get ride status")
async def get_ride(ride_id: str):
    ride = store.get_ride(ride_id)
    if not ride:
        raise HTTPException(404, f"Ride {ride_id} not found")
    return ride


@router.put("/{ride_id}/cancel", summary="Cancel a ride")
async def cancel_ride(ride_id: str):
    ride = store.get_ride(ride_id)
    if not ride:
        raise HTTPException(404, f"Ride {ride_id} not found")
    if ride.status in (RideStatus.COMPLETED, RideStatus.CANCELLED):
        raise HTTPException(400, f"Cannot cancel a {ride.status} ride")

    store.update_ride_status(ride_id, RideStatus.CANCELLED)
    if ride.driver:
        store.set_driver_status(ride.driver.id, DriverStatus.AVAILABLE)
        await manager.send_to_driver(ride.driver.id, {
            "type": "ride_cancelled", "ride_id": ride_id
        })
    await manager.broadcast_to_ride(ride_id, {
        "type": "ride_status", "ride_id": ride_id, "status": "cancelled"
    })
    return {"message": "Ride cancelled"}
