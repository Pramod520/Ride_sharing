"""
WebSocket endpoints
-------------------
ws://host/ws/passenger/{ride_id}     — passenger tracks their ride live
ws://host/ws/driver/{driver_id}      — driver receives assignments & sends GPS
ws://host/ws/dispatcher              — operator sees all drivers in real time

Message format (JSON):
  { "type": "location_update" | "ride_status" | "message" | ..., "data": {...} }
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from datetime import datetime
import json
import asyncio
import logging

from app.services.connection_manager import manager
from app.services.store import store
from app.services.routing import get_route, interpolate_path
from app.models.schemas import RideStatus, DriverStatus

router = APIRouter()
logger = logging.getLogger(__name__)

LIVE_TRACKING_INTERVAL = 1.0   # seconds between position broadcasts during a ride


# ── Passenger WebSocket ───────────────────────────────────────────────────────

@router.websocket("/passenger/{ride_id}")
async def passenger_ws(websocket: WebSocket, ride_id: str):
    """
    Passenger connects here after booking.
    Receives:
      - location_update  : driver GPS coordinates every second
      - ride_status      : status changes (accepted → en_route → arrived → in_progress → completed)
      - eta_update       : updated ETA in seconds
      - message          : text from driver

    The server also runs a coroutine that moves the driver along the OSRM route
    and pushes updates here — simulating real driver GPS in development.
    """
    ride = store.get_ride(ride_id)
    if not ride:
        await websocket.close(code=4004, reason="Ride not found")
        return

    await manager.connect_passenger(ride_id, websocket)

    # Send immediate confirmation
    await websocket.send_json({
        "type":    "ride_status",
        "ride_id": ride_id,
        "status":  ride.status,
        "driver":  ride.driver.model_dump() if ride.driver else None,
        "fare":    ride.fare.model_dump(),
    })

    # Start live tracking simulation for this ride
    tracking_task = asyncio.create_task(
        _simulate_live_tracking(ride_id)
    )

    try:
        while True:
            # Listen for any passenger messages (e.g. "cancel" or chat)
            data = await websocket.receive_text()
            msg  = json.loads(data)
            if msg.get("type") == "cancel":
                store.update_ride_status(ride_id, RideStatus.CANCELLED)
                if ride.driver:
                    store.set_driver_status(ride.driver.id, DriverStatus.AVAILABLE)
                await manager.broadcast_to_ride(ride_id, {
                    "type": "ride_status", "ride_id": ride_id, "status": "cancelled"
                })
    except WebSocketDisconnect:
        pass
    finally:
        tracking_task.cancel()
        manager.disconnect_passenger(ride_id, websocket)
        logger.info(f"Passenger disconnected from ride {ride_id}")


async def _simulate_live_tracking(ride_id: str):
    """
    Moves the assigned driver along the OSRM route and broadcasts
    location + status updates to all passengers watching this ride.

    In production this coroutine is replaced by real GPS from the driver app
    arriving via POST /api/drivers/{id}/location or the driver WebSocket.
    """
    ride = store.get_ride(ride_id)
    if not ride or not ride.driver:
        return

    driver = ride.driver

    # Phase 1: driver travels from their current location to pickup
    driver_loc = driver.location
    pickup_coords, _, pickup_duration = await get_route(driver_loc, ride.pickup)

    await manager.broadcast_to_ride(ride_id, {
        "type":   "ride_status",
        "status": RideStatus.EN_ROUTE,
        "message": f"{driver.name} is on the way to you",
    })
    store.update_ride_status(ride_id, RideStatus.EN_ROUTE)

    await _animate_along_route(ride_id, driver.id, pickup_coords, pickup_duration)

    # Phase 2: arrived at pickup
    await manager.broadcast_to_ride(ride_id, {
        "type":    "ride_status",
        "status":  RideStatus.ARRIVED,
        "message": f"{driver.name} has arrived at your pickup point",
    })
    store.update_ride_status(ride_id, RideStatus.ARRIVED)
    await asyncio.sleep(3)   # simulate waiting for passenger

    # Phase 3: in-progress trip to dropoff
    trip_coords, _, trip_duration = await get_route(ride.pickup, ride.dropoff)

    await manager.broadcast_to_ride(ride_id, {
        "type":    "ride_status",
        "status":  RideStatus.IN_PROGRESS,
        "message": f"Trip started — heading to {ride.dropoff.name or 'destination'}",
    })
    store.update_ride_status(ride_id, RideStatus.IN_PROGRESS)

    await _animate_along_route(ride_id, driver.id, trip_coords, trip_duration)

    # Phase 4: completed
    store.update_ride_status(ride_id, RideStatus.COMPLETED)
    store.set_driver_status(driver.id, DriverStatus.AVAILABLE)

    await manager.broadcast_to_ride(ride_id, {
        "type":    "ride_status",
        "status":  RideStatus.COMPLETED,
        "message": "You have arrived! Thank you for riding with NepRide.",
        "fare":    ride.fare.model_dump(),
    })


async def _animate_along_route(ride_id: str, driver_id: str, coords: list, duration_s: int):
    """Push driver position along a route over duration_s seconds."""
    steps = max(1, duration_s)   # one step per second
    for i in range(steps + 1):
        pos = interpolate_path(coords, i, steps)
        if not pos:
            continue
        lat, lng = pos
        store.update_driver_location(driver_id, lat, lng)

        eta = max(0, duration_s - i)
        await manager.broadcast_to_ride(ride_id, {
            "type":      "location_update",
            "driver_id": driver_id,
            "location":  {"lat": round(lat, 6), "lng": round(lng, 6)},
            "eta_seconds": eta,
            "progress_pct": round((i / steps) * 100),
            "timestamp": datetime.utcnow().isoformat(),
        })
        await asyncio.sleep(LIVE_TRACKING_INTERVAL)


# ── Driver WebSocket ──────────────────────────────────────────────────────────

@router.websocket("/driver/{driver_id}")
async def driver_ws(websocket: WebSocket, driver_id: str):
    """
    Driver app connects here.
    Sends:  { "type": "location", "lat": ..., "lng": ..., "heading": ... }
    Receives: ride assignments, cancellations, messages from dispatcher
    """
    driver = store.get_driver(driver_id)
    if not driver:
        await websocket.close(code=4004, reason="Driver not found")
        return

    await manager.connect_driver(driver_id, websocket)
    store.set_driver_status(driver_id, DriverStatus.AVAILABLE)

    try:
        while True:
            data = await websocket.receive_text()
            msg  = json.loads(data)

            if msg.get("type") == "location":
                lat = msg["lat"]
                lng = msg["lng"]
                store.update_driver_location(driver_id, lat, lng)

                # Forward to any active ride
                for ride in store.rides.values():
                    if (ride.driver and ride.driver.id == driver_id
                            and ride.status not in ("completed", "cancelled")):
                        await manager.broadcast_to_ride(ride.ride_id, {
                            "type":      "location_update",
                            "driver_id": driver_id,
                            "location":  {"lat": round(lat,6), "lng": round(lng,6)},
                            "heading":   msg.get("heading", 0),
                            "speed_kmh": msg.get("speed_kmh", 0),
                            "timestamp": datetime.utcnow().isoformat(),
                        })
                        break

            elif msg.get("type") == "status":
                store.set_driver_status(driver_id, msg["status"])

    except WebSocketDisconnect:
        pass
    finally:
        store.set_driver_status(driver_id, DriverStatus.OFFLINE)
        manager.disconnect_driver(driver_id)
        logger.info(f"Driver {driver_id} disconnected")


# ── Dispatcher WebSocket ──────────────────────────────────────────────────────

@router.websocket("/dispatcher")
async def dispatcher_ws(websocket: WebSocket):
    """
    Dispatcher dashboard connects here.
    Receives all driver GPS updates and ride events in real time.
    """
    await manager.connect_dispatcher(websocket)

    # Send initial state snapshot
    await websocket.send_json({
        "type":    "snapshot",
        "drivers": [d.model_dump() for d in store.all_drivers()],
        "rides":   [r.model_dump() for r in store.rides.values()],
        "stats":   manager.stats(),
    })

    try:
        while True:
            await websocket.receive_text()   # keep-alive ping/pong
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_dispatcher(websocket)
