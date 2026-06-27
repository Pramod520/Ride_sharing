"""
Driver GPS simulator (development only).

Moves available drivers in realistic patterns around Kathmandu.
In production, real driver apps POST location updates via:
  POST /api/drivers/{driver_id}/location
or via the WebSocket at:
  ws://host/ws/driver/{driver_id}

Broadcasts location updates to all connected passengers every second.
"""

import asyncio
import math
import random
import logging
from datetime import datetime

from app.services.store import store
from app.services.connection_manager import manager

logger = logging.getLogger(__name__)

# Kathmandu waypoints drivers wander between
KTM_WAYPOINTS = [
    (27.7172, 85.3240),   # city centre
    (27.7154, 85.3123),   # Thamel
    (27.7215, 85.3620),   # Boudhanath
    (27.7104, 85.3487),   # Pashupatinath
    (27.7089, 85.3152),   # Durbar Marg
    (27.7337, 85.2982),   # Balaju
    (27.6966, 85.3591),   # Airport
    (27.6644, 85.3233),   # Patan
]

BROADCAST_INTERVAL = 1.0   # seconds between GPS pushes
SPEED_KMPH = 25.0          # average city speed


class DriverSimulator:
    def __init__(self):
        # Each driver has a target waypoint they move toward
        self._targets: dict[str, tuple[float, float]] = {}

    async def run(self):
        """Main loop — broadcast GPS every second."""
        while True:
            try:
                await self._tick()
            except Exception as e:
                logger.warning(f"Simulator tick error: {e}")
            await asyncio.sleep(BROADCAST_INTERVAL)

    async def _tick(self):
        active_rides = set(store.rides.keys())

        for driver_id, driver in store.drivers.items():
            # Skip drivers on live rides — their movement is controlled by ride logic
            on_active_ride = any(
                r.driver and r.driver.id == driver_id
                for r in store.rides.values()
                if r.status not in ("completed", "cancelled")
            )
            if on_active_ride:
                continue

            # Pick a new random target if needed
            if driver_id not in self._targets:
                self._targets[driver_id] = random.choice(KTM_WAYPOINTS)

            tlat, tlng = self._targets[driver_id]
            clat = driver.location.lat
            clng = driver.location.lng

            # Move a step toward target
            dlat = tlat - clat
            dlng = tlng - clng
            dist  = math.sqrt(dlat**2 + dlng**2)
            step  = (SPEED_KMPH / 3600) / 111.0   # degrees per second ≈ 1°/111km

            if dist < step * 2:
                # Reached target — pick a new one
                self._targets[driver_id] = random.choice(KTM_WAYPOINTS)
            else:
                new_lat = clat + (dlat / dist) * step
                new_lng = clng + (dlng / dist) * step
                store.update_driver_location(driver_id, new_lat, new_lng)

                # Broadcast to any dispatcher watching
                update = {
                    "type":      "location_update",
                    "driver_id": driver_id,
                    "location":  {"lat": round(new_lat, 6), "lng": round(new_lng, 6)},
                    "timestamp": datetime.utcnow().isoformat(),
                }
                await manager.broadcast_to_dispatchers(update)
