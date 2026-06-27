"""
NepRide — FastAPI Backend
=========================
Real-time ride dispatcher with WebSocket live tracking.

Run:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Docs:
    http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio

from app.routers import rides, drivers, websocket
from app.services.driver_simulator import DriverSimulator

simulator: DriverSimulator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background driver GPS simulator on startup
    global simulator
    simulator = DriverSimulator()
    task = asyncio.create_task(simulator.run())
    app.state.simulator = simulator
    yield
    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="NepRide Dispatcher API",
    description="Real-time ride hailing backend for Nepal — vehicles, routing & live tracking",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rides.router,     prefix="/api/rides",   tags=["Rides"])
app.include_router(drivers.router,   prefix="/api/drivers", tags=["Drivers"])
app.include_router(websocket.router, prefix="/ws",          tags=["WebSocket"])


@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "service": "NepRide API", "version": "1.0.0"}
