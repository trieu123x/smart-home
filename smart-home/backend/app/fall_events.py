"""Persist confirmed AI incidents and notify the existing dashboard."""
import logging
import asyncio
from datetime import datetime

from . import models, services, mqtt_bridge
from .database import SessionLocal
from .realtime import manager
from .push_notify import notify_event

log = logging.getLogger(__name__)
CAMERA_CODE = 'fallguard-camera'


async def camera_heartbeat(status):
    with SessionLocal() as db:
        device = services.get_or_create_device(db, CAMERA_CODE)
        changed = device.name != status['name'] or device.online != (status['state'] == 'connected')
        device.name = status['name']
        device.online = status['state'] == 'connected'
        if device.online:
            device.last_seen = services.utcnow()
        db.commit()
        payload = services.device_payload(device)
    if changed:
        await manager.broadcast('device', payload)


async def record_incident(incident):
    with SessionLocal() as db:
        if db.get(models.FallIncident, incident['key']):
            return
        device = services.get_or_create_device(db, CAMERA_CODE)
        device.name = incident['source']
        device.online = True
        device.last_seen = services.utcnow()
        event = models.Event(device_id=device.id, type='fall_detected', severity='critical',
                             message=(f"{incident['source']} · Phát hiện dấu hiệu té ngã: "
                                      f"người #{incident['person_id']} · Điểm model {incident['score']:.0%}"),
                             ts=datetime.fromisoformat(incident['time']))
        db.add(event)
        db.flush()
        db.add(models.FallIncident(key=incident['key'], event_id=event.id,
                                   person_id=incident['person_id'], score=incident['score']))
        db.commit()
        db.refresh(event)
        payload = services.event_payload(event)
        # Notifications happen after commit. Their failure must not replay the incident.
        try:
            await manager.broadcast('event', payload)
            await mqtt_bridge.fall_alarm()
        except Exception:
            log.exception('Incident saved but live notification failed')
        asyncio.create_task(notify_event(payload))
