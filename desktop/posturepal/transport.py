"""Simulator plus native BLE integration for the Feather Nordic UART service."""

import asyncio
import math
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .domain import Dwell, Frame, Settings
from .firmware import (
    RX_UUID,
    SERVICE_UUID,
    TX_UUID,
    Baseline,
    DeviceState,
    FirmwareCodec,
    ProtocolVersion,
    Readback,
    Reading,
)


@dataclass(frozen=True)
class Ack:
    request_id: int
    source: str
    settings: Settings


class MockTransport(QObject):
    frame = Signal(object)
    acknowledged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)
        self.settings = Settings()
        self.scenario = "Aligned"
        self.custom = (0.0, 0.0)
        self.baseline = (0.0, 0.0)
        self.started = time.monotonic()
        self.sequence = 0
        self.last_raw = None
        self.trackers = [Dwell(), Dwell()]
        self.generation = 0

    def connect_device(self):
        self.timer.start()

    def disconnect_device(self):
        self.timer.stop()
        self.generation += 1
        self.trackers = [Dwell(), Dwell()]

    def request_settings(self, request_id, settings):
        if not self.timer.isActive():
            raise RuntimeError("Simulator is not streaming")
        generation = self.generation

        def acknowledge():
            if generation != self.generation or not self.timer.isActive():
                return
            self.settings = settings
            self.trackers = [Dwell(), Dwell()]
            self.acknowledged.emit(Ack(request_id, "mock", settings))

        QTimer.singleShot(180, self, acknowledge)

    def calibrate(self, reset=False):
        if not self.timer.isActive():
            raise RuntimeError("Connect the simulator before calibration")
        if not reset and self.last_raw is None:
            raise RuntimeError("Waiting for first reading")
        self.baseline = (0.0, 0.0) if reset else self.last_raw
        self.trackers = [Dwell(), Dwell()]

    def _tick(self):
        now = time.monotonic()
        t = now - self.started
        targets = {
            "Aligned": (3, 2),
            "Upper rounding": (25, 3),
            "Lower rounding": (4, 22),
            "Combined rounding": (26, 21),
            "Custom angles": self.custom,
        }
        upper, lower = targets[self.scenario]
        if self.scenario != "Custom angles":
            upper += math.sin(t * 1.4)
            lower += math.sin(t * 1.1) * 0.7
        self.last_raw = upper, lower
        upper -= self.baseline[0]
        lower -= self.baseline[1]
        states = [
            d.update(a, threshold, now, self.settings.dwell_ms)
            for d, a, threshold in zip(
                self.trackers,
                (upper, lower),
                (self.settings.upper_threshold, self.settings.lower_threshold),
            )
        ]
        self.frame.emit(
            Frame.decode(
                dict(
                    version=1,
                    sequence=self.sequence,
                    device_time_ms=t * 1000,
                    upper_deg=upper,
                    lower_deg=lower,
                    upper_state=states[0],
                    lower_state=states[1],
                    battery_pct=86,
                    device_status="ready",
                ),
                now,
            )
        )
        self.sequence += 1


# Async radio work stays on a dedicated thread; Qt signals marshal UI updates.


@dataclass(frozen=True)
class BleProfile:
    notify_uuid: str = TX_UUID
    command_uuid: str = RX_UUID


class BleakTransport:
    """One serialized command at a time; writes never stand in for MCU ACKs."""

    def __init__(
        self,
        address,
        profile=None,
        codec=None,
        on_event=None,
        on_error=None,
        client_factory=None,
    ):
        self.address = address  # Keep the discovered BLEDevice for CoreBluetooth.
        self.profile = profile or BleProfile()
        self.codec = codec or FirmwareCodec()
        self.on_event = on_event or (lambda _: None)
        self.on_error = on_error or (lambda _: None)
        self.client_factory = client_factory
        self.client = None
        self.busy = False
        self.waiter = None
        self.command_error = None
        self.timeout = 5.0

    def _disconnected(self, client):
        if self.client is not client:
            return
        self.client = None
        self.codec = FirmwareCodec()
        if self.waiter and not self.waiter[1].done():
            self.waiter[1].set_exception(ConnectionError("BLE disconnected"))
        self.on_error("BLE disconnected. Reconnect and request status.")

    async def connect(self):
        from bleak import BleakClient

        if self.client is not None:
            raise RuntimeError("Already connected or connecting")
        client = (self.client_factory or BleakClient)(
            self.address, disconnected_callback=self._disconnected
        )
        self.client = client
        self.codec = FirmwareCodec()
        try:
            await client.connect()
            await client.start_notify(self.profile.notify_uuid, self._notification)
            return await self.status()
        except BaseException:
            await self.disconnect()
            raise

    def _notification(self, _sender, data):
        for event in self.codec.feed(bytes(data), time.monotonic()):
            self.on_event(event)
            failure = None
            if isinstance(event, ValueError):
                failure = event
            elif isinstance(event, str) and event.startswith(("ERR ", "ERROR ")):
                failure = RuntimeError(event)
            if failure:
                self.command_error = failure
            if self.waiter:
                predicate, future = self.waiter
                if not future.done():
                    if failure:
                        future.set_exception(failure)
                    elif predicate(event):
                        future.set_result(event)

    async def _write(self, command):
        data = self.codec.encode_command(command)
        client = self.client
        if not client or not client.is_connected:
            raise RuntimeError("Connect first")
        try:
            for start in range(0, len(data), 20):
                await client.write_gatt_char(
                    self.profile.command_uuid, data[start : start + 20], response=True
                )
            await asyncio.sleep(0.1)  # Firmware has a single command mailbox.
        except BaseException:
            await self.disconnect()  # Clear any incomplete peripheral command.
            raise
        if self.command_error:
            raise self.command_error

    async def _exchange(self, command, predicate):
        future = asyncio.get_running_loop().create_future()
        self.waiter = predicate, future
        try:
            await self._write(command)
            return await asyncio.wait_for(future, self.timeout)
        finally:
            self.waiter = None
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()  # Consume errors also raised by _write.

    async def _status(self):
        received = {}

        def collect(event):
            if isinstance(event, (ProtocolVersion, DeviceState, Readback, Baseline)):
                received[type(event)] = event
            return all(
                cls in received
                for cls in (ProtocolVersion, DeviceState, Readback, Baseline)
            )

        await self._exchange("status", collect)
        return received

    async def _run(self, operation):
        if self.busy:
            raise RuntimeError("Wait for the current command to finish")
        if not self.client or not self.client.is_connected:
            raise RuntimeError("Connect first")
        self.busy = True
        self.command_error = None
        try:
            return await operation()
        except (TimeoutError, ValueError):
            # There are no firmware transaction IDs; don't accept delayed replies
            # as evidence for a later command on this same connection.
            await self.disconnect()
            raise
        finally:
            self.busy = False

    async def status(self):
        return await self._run(self._status)

    async def request_settings(self, request_id, settings):
        async def apply():
            await self._exchange(
                self.codec.settings_command(settings),
                lambda e: e == "ACK settings applied; regional timers reset",
            )
            result = await self._status()
            if result[Readback].settings != settings:
                raise RuntimeError("Firmware settings readback differs; inspect status")
            return Ack(request_id, "ble", settings)

        return await self._run(apply)

    async def send(self, command):
        self.codec.encode_command(command)
        if not command.strip():
            raise ValueError("Enter a firmware command")
        if command.split()[0] == "set":
            raise ValueError("Use the feedback settings controls to send set")

        async def execute():
            if command == "status":
                return await self._status()
            await self._write(command)
            return await self._status()

        return await self._run(execute)

    async def disconnect(self):
        client, self.client = self.client, None
        if self.waiter and not self.waiter[1].done():
            self.waiter[1].set_exception(ConnectionError("BLE disconnected"))
        self.codec = FirmwareCodec()
        if client:
            await asyncio.wait_for(client.disconnect(), 3)


class BleWorker(QThread):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.loop = asyncio.new_event_loop()

    def run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            tasks = asyncio.all_tasks(self.loop)
            for task in tasks:
                task.cancel()
            if tasks:
                self.loop.run_until_complete(
                    asyncio.gather(*tasks, return_exceptions=True)
                )
            self.loop.close()


class BluetoothTransport(QObject):
    frame = Signal(object)
    acknowledged = Signal(object)
    event = Signal(object)
    devices_found = Signal(object)
    connection = Signal(bool)
    error = Signal(str)
    finished = Signal()
    _received = Signal(object)
    _lost = Signal(object)
    _completed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.adapter = None
        self.connected = False
        self.busy = False
        self.settings = None
        self.baseline = (None, None)
        self.state = "UNKNOWN"
        self.fault_reason = None
        self._baseline_refresh_needed = False
        self.sequence = 0
        self.generation = 0
        self.cleanup_future = None
        self._received.connect(self._on_event)
        self._lost.connect(self._on_lost)
        self._completed.connect(self._on_completed)
        self.finished.connect(self._refresh_calibration_status)

    def _submit(self, operation, kind="command"):
        if self.busy:
            operation.close()
            raise RuntimeError("Wait for the current BLE operation to finish")
        if self.worker is None:
            self.worker = BleWorker(self)
            self.worker.start()
        self.busy = True
        generation = self.generation
        future = asyncio.run_coroutine_threadsafe(operation, self.worker.loop)

        def done(result):
            try:
                outcome = result.result()
            except BaseException as exc:
                outcome = exc
            self._completed.emit((generation, kind, outcome))

        future.add_done_callback(done)
        return future

    def _on_completed(self, completion):
        generation, kind, result = completion
        if generation != self.generation:
            return
        self.busy = False
        if isinstance(result, BaseException):
            self.error.emit(
                str(result)
                or "BLE response timed out; reconnect to reconcile device state"
            )
            if self.adapter and self.adapter.client is None:
                self._on_lost("BLE disconnected")
        elif isinstance(result, list):
            self.devices_found.emit(result)
        elif isinstance(result, Ack):
            self.acknowledged.emit(result)
        elif kind == "connect":
            self.connected = True
            self.connection.emit(True)
        self.finished.emit()

    def scan(self):
        async def discover():
            from bleak import BleakScanner

            found = await BleakScanner.discover(
                timeout=5, return_adv=True, service_uuids=[SERVICE_UUID]
            )
            return [
                device
                for device, adv in found.values()
                if SERVICE_UUID in [u.lower() for u in adv.service_uuids]
            ]

        self._submit(discover())

    def connect_device(self, device):
        if self.busy or self.connected:
            raise RuntimeError("Disconnect or wait before connecting")
        generation = self.generation
        self.settings = None
        self.baseline = (None, None)
        self.state = "UNKNOWN"
        self.fault_reason = None
        self._baseline_refresh_needed = False
        self.sequence = 0
        self.adapter = BleakTransport(
            device,
            on_event=lambda e: self._received.emit((generation, e)),
            on_error=lambda e: self._lost.emit((generation, e)),
        )
        self._submit(self.adapter.connect(), "connect")

    def _on_event(self, incoming):
        generation, event = incoming
        if generation != self.generation:
            return
        if isinstance(event, Readback):
            self.settings = event.settings
        elif isinstance(event, Baseline):
            self.baseline = (
                event.angles if event.angles and self.state != "FAULT" else (None, None)
            )
            if event.angles and self.state in ("MONITORING", "ALERT"):
                self._baseline_refresh_needed = False
        elif isinstance(event, DeviceState):
            previous_state = self.state
            self.state = event.state
            if event.state == "FAULT":
                self.fault_reason = event.fault_reason or self.fault_reason
                self.baseline = (None, None)
            else:
                self.fault_reason = None
            if event.state in ("FAULT", "SETTLING", "CALIBRATING"):
                self.baseline = (None, None)
                self._baseline_refresh_needed = False
            elif event.state == "MONITORING" and previous_state in (
                "SETTLING",
                "CALIBRATING",
            ):
                self._baseline_refresh_needed = True
                QTimer.singleShot(0, self._refresh_calibration_status)
        elif (
            isinstance(event, Reading)
            and self.connected
            and self.state in ("MONITORING", "ALERT")
        ):
            states = ("unknown", "unknown")
            if self.settings:
                states = tuple(
                    "above" if abs(a) > t else "aligned"
                    for a, t in (
                        (event.upper, self.settings.upper_threshold),
                        (event.lower, self.settings.lower_threshold),
                    )
                )
            self.frame.emit(
                Frame(
                    self.sequence,
                    None,
                    event.received_at,
                    event.upper,
                    event.lower,
                    *states,
                    None,
                    self.state.lower(),
                    event.buzz,
                )
            )
            self.sequence += 1
        self.event.emit(event)

    def _refresh_calibration_status(self):
        if (
            self._baseline_refresh_needed
            and self.connected
            and not self.busy
            and self.adapter
            and self.state in ("MONITORING", "ALERT")
        ):
            self._baseline_refresh_needed = False
            self._submit(self.adapter.status())
            self.event.emit("APP: Reading calibrated baseline from firmware")

    def _on_lost(self, incoming):
        if isinstance(incoming, tuple):
            generation, message = incoming
            if generation != self.generation:
                return
        else:
            message = incoming
        self.generation += 1
        self.busy = False
        self.connected = False
        self.settings = None
        self.baseline = (None, None)
        self.state = "UNKNOWN"
        self.fault_reason = None
        self._baseline_refresh_needed = False
        self.connection.emit(False)
        self.error.emit(message)

    def request_settings(self, request_id, settings):
        if not self.adapter:
            raise RuntimeError("Connect first")
        self._submit(self.adapter.request_settings(request_id, settings))
        self.settings = None  # Effective values are uncertain until readback.

    def command(self, command):
        if not self.adapter:
            raise RuntimeError("Connect first")
        self._submit(self.adapter.send(command))

    def calibrate(self, reset=False):
        if reset:
            raise RuntimeError(
                "Firmware has no reset-baseline command; calibrate again"
            )
        self.command("calibrate")

    def disconnect_device(self):
        self.generation += 1  # Ignore queued frames and completions from the old link.
        self.connected = False
        self.busy = False
        self.settings = None
        self.baseline = (None, None)
        self.state = "UNKNOWN"
        self.fault_reason = None
        self._baseline_refresh_needed = False
        adapter, self.adapter = self.adapter, None
        if adapter and self.worker:
            self.cleanup_future = self._submit(adapter.disconnect(), "disconnect")
        self.connection.emit(False)

    def shutdown(self):
        adapter, self.adapter = self.adapter, None
        self.generation += 1
        if self.worker:

            async def stop():
                try:
                    if adapter:
                        await adapter.disconnect()
                    if self.cleanup_future:
                        await asyncio.wrap_future(self.cleanup_future)
                finally:
                    asyncio.get_running_loop().stop()

            asyncio.run_coroutine_threadsafe(stop(), self.worker.loop)
            self.worker.wait(5000)
            self.worker = None
