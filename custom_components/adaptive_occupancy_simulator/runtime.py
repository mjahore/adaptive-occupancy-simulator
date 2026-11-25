"""Event-driven execution, learning and persistence for one household."""

import asyncio
import hashlib
import json
import logging
import math
import random
from collections import deque
from datetime import UTC, datetime, time, timedelta
from functools import partial
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import elevation
from homeassistant.core import Context, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_point_in_utc_time, async_track_state_change_event
from homeassistant.helpers.storage import Store

from .archive import Archive
from .const import DOMAIN, LIGHTING_DOMAINS, STEP_SECONDS, occupancy_reason, settings, validate
from .entity import is_own_entity, own_entities
from .history import import_recorder
from .model import Action, Frame, HybridModel, constrain

_LOGGER = logging.getLogger(__name__)


class Runtime:
    """One pending action timer; stop paths never issue a light command."""

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.config = settings(entry.data, entry.options)
        validate(self.config, forbidden_entities=own_entities(hass))
        self.tz = ZoneInfo(hass.config.time_zone)
        self.observer = Observer(hass.config.latitude, hass.config.longitude, hass.config.elevation)
        identity = {
            k: self.config[k]
            for k in ("lights", "persons", "alarm", "legacy_automations", "home_states", "away_states")
        }
        identity["location"] = [hass.config.latitude, hass.config.longitude, hass.config.time_zone]
        self.fingerprint = hashlib.sha256(
            json.dumps({**self.config, **identity}, sort_keys=True).encode()
        ).hexdigest()
        self.archive = Archive(hass.config.path(".storage", f"{DOMAIN}_{entry.entry_id}.sqlite"), identity)
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.plan_store = Store(hass, 1, f"{DOMAIN}.plan.{entry.entry_id}")
        self.enabled = False
        self.dry_run = True
        self.closed = False
        self.busy = False
        self.error = ""
        self.model = None
        self.summary = {}
        self.plan = []
        self.plan_day = ""
        self.seed = random.SystemRandom().randrange(2**53)
        self.generation = 0
        self.cursor = 0
        self.session_id = None
        self.listeners = set()
        self.unsubscribers = []
        self.tasks = set()
        self.action_task = None
        self.action_timer = None
        self.sample_timer = None
        self.prepare_task = None
        self.training_lock = asyncio.Lock()
        self.control_lock = asyncio.Lock()
        self.plan_lock = asyncio.Lock()
        self.own_contexts = deque(maxlen=512)
        self.overrides = {}
        self.live_on_since = {}
        self.limit_retry = {}
        self.last_commands = {}
        self.log = deque(maxlen=100)
        self.sample = None
        self.tainted = "startup_partial_interval"
        self.last_train_day = ""
        self.aos_entity = None

    def now(self):
        return datetime.now(UTC)

    def states(self):
        ids = (
            self.config["persons"]
            + self.config["lights"]
            + self.config["legacy_automations"]
            + [self.config["alarm"]]
        )
        return {e: (state.state if (state := self.hass.states.get(e)) else None) for e in ids}

    def feature(self, stamp):
        instant = datetime.fromtimestamp(stamp, UTC)
        local = instant.astimezone(self.tz)
        return (
            local.hour * 60 + local.minute,
            int(local.weekday() >= 5),
            round(elevation(self.observer, instant), 2),
        )

    def reason(self):
        if not self.enabled:
            return "disabled"
        if self.error:
            return "error"
        why = occupancy_reason(self.states(), self.config)
        if why:
            return why
        if not self.model or not self.model.ready:
            return "insufficient_history"
        return ""

    @property
    def status(self):
        why = self.reason()
        return why or ("dry_run" if self.dry_run else "simulating")

    def snapshot(self):
        return {
            "fingerprint": self.fingerprint,
            "enabled": self.enabled,
            "dry_run": self.dry_run,
            "plan_day": self.plan_day,
            "seed": self.seed,
            "cursor": self.cursor,
            "session_id": self.session_id,
            "overrides": self.overrides,
            "live_on_since": self.live_on_since,
            "last_commands": self.last_commands,
            "log": list(self.log),
        }

    def publish(self):
        if not self.closed:
            for listener in tuple(self.listeners):
                listener()

    def save_later(self):
        if not self.closed:
            self.store.async_delay_save(self.snapshot, 1)

    def record(self, result, action=None, detail=""):
        item = {"time": self.now().isoformat(), "result": result, "detail": detail}
        if action:
            item.update(entity=action.entity_id, action="on" if action.on else "off", source=action.source)
        self.log.appendleft(item)
        self.save_later()
        self.publish()

    def spawn(self, coro, name):
        task = self.hass.async_create_background_task(coro, f"AOS {name}")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def initialize(self):
        await self.hass.async_add_executor_job(self.archive.initialize)
        saved = await self.store.async_load() or {}
        saved_plan = await self.plan_store.async_load() or {}
        if saved.get("fingerprint") == self.fingerprint:
            self.enabled = bool(saved.get("enabled", False))
            self.dry_run = bool(saved.get("dry_run", True))
            self.seed = saved.get("seed", self.seed)
            if (
                saved_plan.get("fingerprint") == self.fingerprint
                and saved_plan.get("seed") == self.seed
                and saved_plan.get("day") == saved.get("plan_day")
            ):
                self.plan = [Action(**a) for a in saved_plan.get("actions", [])]
                self.plan_day = saved.get("plan_day", "")
                self.cursor = int(saved.get("cursor", 0))
            self.session_id = saved.get("session_id")
            self.overrides = saved.get("overrides", {})
            self.live_on_since = saved.get("live_on_since", {})
            self.last_commands = saved.get("last_commands", {})
            self.log.extend(saved.get("log", [])[:100])
        elif saved.get("session_id"):
            await self.hass.async_add_executor_job(
                self.archive.close_exclusion, saved["session_id"], int(self.now().timestamp())
            )
        await self.hass.async_add_executor_job(
            self.archive.close_abandoned_sessions,
            self.session_id if self.enabled else None,
            (int(self.now().timestamp()) // STEP_SECONDS + 1) * STEP_SECONDS,
        )
        if not self.enabled:
            self.session_id = None
        watched = list(self.states())
        self.unsubscribers.append(async_track_state_change_event(self.hass, watched, self.state_changed))
        self._begin_sample()
        self._schedule_sample()
        # Runtime can restore an intent, but never replay missed events.
        self._advance_cursor()
        self.state_changed(None)

    def _begin_sample(self):
        stamp = int(self.now().timestamp()) // STEP_SECONDS * STEP_SECONDS
        states = self.states()
        mask = sum(1 << i for i, entity in enumerate(self.config["lights"]) if states.get(entity) == "on")
        minute, weekend, solar = self.feature(stamp)
        self.sample = Frame(stamp, mask, minute, weekend, solar)

    def _learning_reason(self):
        states = self.states()
        why = occupancy_reason(states, self.config, learning=True, enabled=self.enabled)
        if not why and any(states.get(e) not in {"on", "off"} for e in self.config["lights"]):
            why = "light_unknown"
        return why

    def _schedule_sample(self):
        next_ts = (int(self.now().timestamp()) // STEP_SECONDS + 1) * STEP_SECONDS
        self.sample_timer = async_track_point_in_utc_time(
            self.hass, self._sample_tick, datetime.fromtimestamp(next_ts, UTC)
        )

    async def _sample_tick(self, now):
        if self.closed:
            return
        self.sample_timer = None
        why = self.tainted or self._learning_reason()
        old = self.sample
        if old and int(now.timestamp()) - old.ts >= STEP_SECONDS * 2:
            why = "sampling_gap"
        # Rotate before awaiting disk I/O so concurrent events taint the NEW slot.
        self._begin_sample()
        self.tainted = self._learning_reason()
        self._schedule_sample()
        if old:
            frame = Frame(old.ts, old.mask, old.minute, old.weekend, old.elevation, not bool(why), why)
            try:
                await self.hass.async_add_executor_job(partial(self.archive.write, [frame], replace=True))
            except Exception as err:
                self.fail("archive_write", err)
                return
        today = self.now().astimezone(self.tz).date().isoformat()
        if self.last_train_day != today and not self.busy:
            self.spawn(self.train(), "daily training")
        self.reconcile()
        self.publish()

    @callback
    def state_changed(self, event):
        if self.closed:
            return
        self.tainted = self.tainted or self._learning_reason()
        if event:
            entity = event.data["entity_id"]
            new = event.data.get("new_state")
            old = event.data.get("old_state")
            if entity in self.config["lights"] and self.enabled and old and new:
                if (
                    (old.state != new.state or old.attributes != new.attributes)
                    and new.context.id not in self.own_contexts
                    and new.context.parent_id not in self.own_contexts
                ):
                    self.overrides[entity] = (
                        self.now().timestamp() + self.config["manual_override_minutes"] * 60
                    )
                    self.live_on_since.pop(entity, None)
                    self.record("manual_override", detail=entity)
        # Check every resident directly, even when another resident is unknown.
        if self.enabled and any(self.states().get(e) == "home" for e in self.config["persons"]):
            self.enabled = False
            self.cancel_pending()
            self.record("stopped", detail="resident_home; lights unchanged")
            self.spawn(self._finish_stop(), "persist return")
        self.reconcile()

    def cancel_pending(self):
        self.generation += 1
        if self.action_timer:
            self.action_timer()
            self.action_timer = None
        if self.action_task and self.action_task is not asyncio.current_task():
            self.action_task.cancel()
        self.action_task = None

    def reconcile(self):
        if self.closed:
            return
        if self.reason():
            self.cancel_pending()
        elif not self.prepare_task or self.prepare_task.done():
            self.prepare_task = self.spawn(self._prepare(), "schedule")
        self.publish()

    async def _prepare(self):
        try:
            await self.generate_plan()
            if not self.closed and not self.reason() and not self.action_timer and not self.action_task:
                self._arm_next()
        except Exception as err:
            self.fail("schedule", err)

    def _advance_cursor(self):
        now = self.now().timestamp()
        while self.cursor < len(self.plan) and self.plan[self.cursor].ts < now:
            self.cursor += 1

    def _arm_next(self):
        if self.closed or self.reason():
            return
        self._advance_cursor()
        now = self.now().timestamp()
        deadlines = [
            max(since + self.config["maximum_on_minutes"] * 60, self.limit_retry.get(entity, 0), now + 0.01)
            for entity, since in self.live_on_since.items()
            if not self.dry_run
        ]
        if self.cursor < len(self.plan):
            deadlines.append(self.plan[self.cursor].ts)
        if not deadlines:
            return
        token = self.generation

        @callback
        def fire(now):
            self.action_timer = None
            if token == self.generation and not self.reason() and not self.closed:
                self.action_task = self.spawn(self._execute_due(token), "light action")

        self.action_timer = async_track_point_in_utc_time(
            self.hass, fire, datetime.fromtimestamp(min(deadlines), UTC)
        )

    async def _execute_due(self, token):
        try:
            now = self.now().timestamp()
            for entity, since in list(self.live_on_since.items()):
                if now - since >= self.config["maximum_on_minutes"] * 60:
                    self.limit_retry[entity] = now + 60
                    await self.dispatch(Action(int(now), entity, False, "maximum_on_limit"), token)
            while self.cursor < len(self.plan) and self.plan[self.cursor].ts <= now + 0.25:
                if self.closed or token != self.generation or self.reason():
                    return
                action = self.plan[self.cursor]
                self.cursor += 1
                # Persist consumption BEFORE dispatch: prefer a missed command to
                # replay after power loss. Recheck interlocks after this await.
                await self.store.async_save(self.snapshot())
                if now - action.ts > 60:
                    self.record("skipped_late", action)
                    continue
                await self.dispatch(action, token)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            self.fail("execution", err)
        finally:
            self.action_task = None
            if token == self.generation and not self.closed and not self.reason():
                self._arm_next()

    async def dispatch(self, action, token):
        """The final gate is immediately adjacent to HA's service dispatch."""
        if self.closed or token != self.generation or self.reason():
            return
        now = self.now().timestamp()
        entity = action.entity_id
        if entity not in self.config["lights"]:
            raise HomeAssistantError("Schedule contains an unconfigured entity")
        domain = entity.partition(".")[0]
        if domain not in LIGHTING_DOMAINS or is_own_entity(self.hass, entity):
            raise HomeAssistantError("Schedule contains an unsupported lighting target")
        if self.overrides.get(entity, 0) > now:
            self.record("skipped_override", action)
            return
        state = self.hass.states.get(entity)
        if not state or state.state not in {"on", "off"}:
            self.record("skipped_unavailable", action)
            return
        if self.dry_run:
            self.record("would_call", action)
            return
        if state.state == ("on" if action.on else "off"):
            if not action.on:
                self.live_on_since.pop(entity, None)
            self.record("already_set", action)
            return
        if action.on:
            active = {
                e
                for e in self.config["lights"]
                if self.hass.states.get(e) is not None and self.hass.states.get(e).state == "on"
            }
            count = len(active | set(self.live_on_since))
            if count >= self.config["maximum_lights_on"]:
                self.record("skipped_limit", action)
                return
        previous = self.last_commands.get(entity)
        if previous and now - previous < self.config["minimum_dwell_minutes"] * 60:
            self.record("skipped_dwell", action)
            return
        context = Context()
        self.own_contexts.append(context.id)
        # No intervening await after the safety gate; this is a single event-loop
        # turn. A device command already sent cannot be recalled on arrival.
        if self.closed or token != self.generation or self.reason() or self.dry_run:
            return
        await self.hass.services.async_call(
            domain,
            "turn_on" if action.on else "turn_off",
            {"entity_id": entity},
            blocking=True,
            context=context,
        )
        self.last_commands[entity] = now
        if action.on:
            self.live_on_since[entity] = now
        else:
            self.live_on_since.pop(entity, None)
        self.record("called", action)

    async def set_enabled(self, value):
        async with self.control_lock:
            if value:
                if any(self.states().get(e) == "home" for e in self.config["persons"]):
                    raise HomeAssistantError(
                        "AOS cannot be enabled while a resident is home. Use Regenerate preview instead."
                    )
                if not self.enabled:
                    # Record the exclusion before enabling, including dry runs.
                    self.session_id = await self.hass.async_add_executor_job(
                        self.archive.exclude,
                        int(self.now().timestamp()) // STEP_SECONDS * STEP_SECONDS,
                        32503680000,
                        "AOS enabled session",
                    )
                    if self.closed or any(self.states().get(e) == "home" for e in self.config["persons"]):
                        await self._finish_stop()
                        return
                    self.enabled = True
            else:
                self.enabled = False
                self.cancel_pending()
                await self._finish_stop()
            try:
                await self.store.async_save(self.snapshot())
            except Exception:
                self.enabled = False
                self.cancel_pending()
                raise
            self.record("enabled" if self.enabled else "stopped", detail="lights unchanged")
            self.reconcile()

    async def _finish_stop(self):
        self.live_on_since.clear()
        self.limit_retry.clear()
        session = self.session_id
        self.session_id = None
        if session:
            # Include the partial last interval in the exclusion.
            end = (int(self.now().timestamp()) // STEP_SECONDS + 1) * STEP_SECONDS
            await self.hass.async_add_executor_job(self.archive.close_exclusion, session, end)
        await self.store.async_save(self.snapshot())
        self.publish()

    async def set_dry_run(self, value):
        if self.enabled:
            raise HomeAssistantError("Stop AOS before changing dry-run mode")
        self.cancel_pending()
        self.dry_run = value
        try:
            await self.store.async_save(self.snapshot())
        except Exception:
            # Failed persistence must never authorize real output in memory.
            self.dry_run = True
            self.publish()
            raise
        self.publish()

    def fail(self, operation, error):
        self.error = f"{operation}: {type(error).__name__}: {error}"
        self.cancel_pending()
        self.record("error", detail=self.error)
        _LOGGER.exception("AOS %s failed; lighting suspended", operation)

    async def train(self, import_history=False):
        if self.training_lock.locked() or self.closed:
            return
        async with self.training_lock:
            self.busy = True
            self.publish()
            try:
                if import_history:
                    await import_recorder(
                        self.hass,
                        self.config,
                        self.archive,
                        self.feature,
                        lambda: not self.closed,
                        self.aos_entity,
                    )
                if self.closed:
                    return
                cutoff = int(self.now().timestamp()) - self.config["retention_days"] * 86400
                await self.hass.async_add_executor_job(self.archive.prune, cutoff)
                frames = await self.hass.async_add_executor_job(self.archive.read)
                model = await self.hass.async_add_executor_job(HybridModel, frames, self.config, self.tz)
                summary = await self.hass.async_add_executor_job(self.archive.summary)
                if self.closed:
                    return
                self.model = model
                self.summary = summary
                self.error = ""
                self.last_train_day = self.now().astimezone(self.tz).date().isoformat()
                await self.generate_plan()
                self.record("trained", detail=f"{model.days} eligible days")
            except asyncio.CancelledError:
                raise
            except Exception as err:
                self.fail("training", err)
            finally:
                self.busy = False
                self.reconcile()

    def _make_plan(self, day, seed):
        start = datetime.combine(day, time.min, self.tz)
        end = datetime.combine(day + timedelta(days=1), time.min, self.tz)
        targets = []
        for ts in range(int(start.timestamp()), int(end.timestamp()), STEP_SECONDS):
            minute, weekend, solar = self.feature(ts)
            targets.append(Frame(ts, 0, minute, weekend, solar))
        trajectory = self.model.generate(targets, seed)
        return constrain(trajectory, self.config["lights"], self.config, seed)

    async def generate_plan(self, force=False):
        async with self.plan_lock:
            day = self.now().astimezone(self.tz).date()
            if not self.model or not self.model.ready or self.closed:
                return
            if not force and self.plan_day == day.isoformat():
                return
            self.cancel_pending()
            self.seed = random.SystemRandom().randrange(2**53)
            plan = await self.hass.async_add_executor_job(self._make_plan, day, self.seed)
            if self.closed:
                return
            self.plan, self.plan_day, self.cursor = plan, day.isoformat(), 0
            self._advance_cursor()
            # The large immutable plan is written once, independently of the
            # small consumed-action cursor saved before each device command.
            await self.plan_store.async_save(
                {
                    "fingerprint": self.fingerprint,
                    "seed": self.seed,
                    "day": self.plan_day,
                    "actions": [a.as_dict() for a in self.plan],
                }
            )
            await self.store.async_save(self.snapshot())
            self.publish()

    async def regenerate(self):
        await self.generate_plan(force=True)
        self.reconcile()

    async def exclude(self, start, end, reason):
        await self.set_enabled(False)
        async with self.training_lock:
            self.model = None
            self.plan, self.plan_day, self.cursor = [], "", 0
            start = int(start.timestamp()) // STEP_SECONDS * STEP_SECONDS
            end = math.ceil(end.timestamp() / STEP_SECONDS) * STEP_SECONDS
            await self.hass.async_add_executor_job(self.archive.exclude, start, end, reason)
            await self.store.async_save(self.snapshot())
        await self.train()

    async def shutdown(self):
        if self.closed:
            return
        self.closed = True
        self.cancel_pending()
        if self.sample_timer:
            self.sample_timer()
        for unsub in self.unsubscribers:
            unsub()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.store.async_save(self.snapshot())
        self.listeners.clear()
