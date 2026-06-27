"""
WebSocket connection manager.

Maintains a registry of active connections keyed by ride_id and driver_id.
Broadcasts GPS updates to all subscribers of a ride.
"""

from fastapi import WebSocket
from typing import Dict, List, Set
import json
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # ride_id → list of passenger WebSocket connections
        self.ride_connections: Dict[str, List[WebSocket]] = {}
        # driver_id → single driver WebSocket connection
        self.driver_connections: Dict[str, WebSocket] = {}
        # dispatcher connections (see all rides)
        self.dispatcher_connections: Set[WebSocket] = set()

    # ── Passenger ─────────────────────────────────────────────────────────────

    async def connect_passenger(self, ride_id: str, ws: WebSocket):
        await ws.accept()
        self.ride_connections.setdefault(ride_id, []).append(ws)
        logger.info(f"Passenger connected to ride {ride_id}")

    def disconnect_passenger(self, ride_id: str, ws: WebSocket):
        if ride_id in self.ride_connections:
            self.ride_connections[ride_id] = [
                c for c in self.ride_connections[ride_id] if c != ws
            ]
            if not self.ride_connections[ride_id]:
                del self.ride_connections[ride_id]

    async def broadcast_to_ride(self, ride_id: str, message: dict):
        """Send a message to all passengers watching a ride."""
        dead = []
        for ws in self.ride_connections.get(ride_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_passenger(ride_id, ws)

    # ── Driver ────────────────────────────────────────────────────────────────

    async def connect_driver(self, driver_id: str, ws: WebSocket):
        await ws.accept()
        self.driver_connections[driver_id] = ws
        logger.info(f"Driver {driver_id} connected")

    def disconnect_driver(self, driver_id: str):
        self.driver_connections.pop(driver_id, None)

    async def send_to_driver(self, driver_id: str, message: dict):
        ws = self.driver_connections.get(driver_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect_driver(driver_id)

    # ── Dispatcher ────────────────────────────────────────────────────────────

    async def connect_dispatcher(self, ws: WebSocket):
        await ws.accept()
        self.dispatcher_connections.add(ws)

    def disconnect_dispatcher(self, ws: WebSocket):
        self.dispatcher_connections.discard(ws)

    async def broadcast_to_dispatchers(self, message: dict):
        dead = []
        for ws in self.dispatcher_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_dispatcher(ws)

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "active_rides":       len(self.ride_connections),
            "connected_drivers":  len(self.driver_connections),
            "dispatchers_online": len(self.dispatcher_connections),
        }


# Global singleton
manager = ConnectionManager()
