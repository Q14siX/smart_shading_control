"""Runtime controller for Smart Shading Control."""

from __future__ import annotations

import asyncio
import logging
import random
from collections import deque
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from math import isfinite
from typing import Any

from aiohttp import ClientError
from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    EVENT_HOMEASSISTANT_STARTED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Context, CoreState, Event, HomeAssistant, State, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util

from .command_queue import (
    PRIORITY_AUTOMATIC,
    PRIORITY_EMERGENCY,
    PRIORITY_MANUAL,
    PRIORITY_MANUAL_STOP,
    PRIORITY_SAFETY,
    PRIORITY_TILT,
    CommandResult,
    get_command_queue,
)
from .const import (
    COMMAND_GRACE_SECONDS,
    CONF_AZIMUTH_NORTH,
    CONF_COMFORT_TEMPERATURE,
    CONF_COVER_CONTACTS,
    CONF_COVERS_EAST,
    CONF_COVERS_NORTH,
    CONF_COVERS_SOUTH,
    CONF_COVERS_WEST,
    CONF_DRY_RUN,
    CONF_DST_AMBIGUOUS_POLICY,
    CONF_DST_NONEXISTENT_POLICY,
    CONF_ENTRY_TYPE,
    CONF_EVALUATION_INTERVAL,
    CONF_FORECAST_HOURS,
    CONF_FORECAST_THRESHOLD,
    CONF_FROST_ACTION,
    CONF_FROST_SAFE_POSITION,
    CONF_GLOBAL_POSITION_VALUES,
    CONF_HEAT_POSITION,
    CONF_HEAT_TEMPERATURE,
    CONF_ILLUMINANCE_SENSOR,
    CONF_IRRADIANCE_SENSOR,
    CONF_MANUAL_OVERRIDE_MINUTES,
    CONF_MIN_MOVE_INTERVAL,
    CONF_MIN_POSITION_CHANGE,
    CONF_MIN_SUN_ELEVATION,
    CONF_OPEN_POSITION,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_PREVENTIVE_POSITION,
    CONF_RAIN_SAFE_POSITION,
    CONF_RAIN_SENSOR,
    CONF_RISK_HYSTERESIS,
    CONF_ROOM_NAME,
    CONF_ROOM_TEMP_SENSOR,
    CONF_RULE_DAY_TYPE,
    CONF_RULE_ENABLED,
    CONF_RULE_SCOPE,
    CONF_STORM_SAFE_POSITION,
    CONF_STRONG_HEAT_POSITION,
    CONF_STRONG_HEAT_TEMPERATURE,
    CONF_SUN_ENTITY,
    CONF_SUN_EVENT_SOURCE,
    CONF_SUN_HALF_ANGLE,
    CONF_TILT_CONTROL_ENABLED,
    CONF_TILT_DEFAULT_POSITION,
    CONF_TILT_HEAT_POSITION,
    CONF_TILT_SAFETY_POSITION,
    CONF_TILT_STRONG_HEAT_POSITION,
    CONF_TIME_RULE_CLOSE_POSITION,
    CONF_TIME_RULES,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SAFE_POSITION,
    CONF_WIND_SENSOR,
    CONF_WORKDAY_ENTITY,
    CONTACT_CLOSED,
    CONTACT_OPEN,
    CONTACT_TILTED,
    CONTACT_UNKNOWN,
    DAY_TYPE_ANY,
    DEFAULTS,
    DOMAIN,
    ENTRY_TYPE_GLOBAL,
    FORECAST_REFRESH_MINUTES,
    FROST_ACTION_SAFE_POSITION,
    GLOBAL_DEFAULTS,
    MODE_AUTOMATIC,
    MODE_CLOSED,
    MODE_HEAT_PROTECTION,
    MODE_OPEN,
    MODE_PAUSE,
    POSITION_DEFAULTS,
    POSITION_SETTING_KEYS,
    POSITION_TOLERANCE,
    RULE_ACTION_CLOSE,
    RULE_ACTION_OPEN,
    RULE_SCOPE_ROOM,
    SIGNAL_UPDATE,
    STATUS_CONTACT_PROTECTION,
    STATUS_DISABLED,
    STATUS_DRY_RUN,
    STATUS_HEAT_PROTECTION,
    STATUS_MANUAL_OVERRIDE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    STATUS_PREVENTIVE,
    STATUS_SCHEDULE,
    STATUS_SOLAR_GAIN,
    STATUS_STRONG_HEAT,
    STATUS_UNAVAILABLE,
    SUN_EVENT_SOURCE_ENTITY,
)
from .contacts import (
    classify_contact_state,
    resolve_night_close_contact,
    summarize_cover_contacts,
)
from .coordinator import COORDINATOR_KEY, SmartShadingDataCoordinator
from .decision_history import DecisionHistory
from .global_repairs import update_global_repairs
from .issues import create_issue, delete_issue, delete_stale_entity_issues
from .logic import (
    allow_solar_gain,
    as_list,
    binary_cover_target,
    calculate_heat_risk,
    choose_dynamic_level,
    clamp,
    facade_azimuths,
    forecast_max_temperature,
    is_opening_target,
    manual_movement_trigger,
    sun_incidence,
)
from .runtime_state import (
    parse_aware_utc_timestamp,
    parse_utc_timestamp,
    restore_future_timestamps,
    restore_origin_markers,
    restore_pending_target_commands,
    restore_recent_target_commands,
    restore_temperature_samples,
)
from .schedule import normalize_boolean, resolve_rule_actions, resolve_rule_states
from .schedule_conflicts import detect_rule_conflicts
from .state_helpers import (
    attribute_float,
    position_from_state,
    temperature_to_celsius,
    tilt_position_from_state,
)
from .storage_helpers import async_load_persistent_store
from .weather_runtime import WeatherRuntime

_LOGGER = logging.getLogger(__name__)


def _time_rule_occurrence_sort_key(value: str) -> str:
    """Return the UTC timestamp segment used to retain newest occurrences."""
    parts = str(value).split(":", 2)
    return parts[2] if len(parts) == 3 else str(value)


_COMMAND_RETRY_DELAYS = (10, 30, 90, 300, 600)
_MAX_COMMAND_RETRIES = len(_COMMAND_RETRY_DELAYS)
_FORECAST_STALE_MINUTES = max(90, FORECAST_REFRESH_MINUTES * 3)
_TIME_RULE_OPEN_RETRY_MINUTES = 30
_TIME_RULE_CLOSE_CONTACT_DELAY_SECONDS = 30
_MANUAL_POSITION_CHANGE_THRESHOLD = 2
_PENDING_TARGET_HORIZON = timedelta(minutes=15)

_ORIENTATION_CONFIG = {
    "north": CONF_COVERS_NORTH,
    "east": CONF_COVERS_EAST,
    "south": CONF_COVERS_SOUTH,
    "west": CONF_COVERS_WEST,
}


class SmartShadingController:
    """Coordinate sensors, decisions and cover commands for one room."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.enabled = True
        self.mode = MODE_AUTOMATIC
        self.data: dict[str, Any] = {
            "status": STATUS_UNAVAILABLE,
            "reason": "initializing",
            "reason_code": "initializing",
            "reason_context": {},
            "decision_trace": [],
            "dry_run": False,
            "would_command_positions": {},
            "would_command_tilt_positions": {},
            "provider_health": {"state": "ok", "consecutive_failures": 0},
            "provider_health_by_cover": {},
            "provider_failures": 0,
            "last_provider_error": None,
            "last_provider_error_at": None,
            "next_provider_retry": None,
            "last_successful_command": None,
            "command_queue": {},
            "command_queue_depth": 0,
            "command_queue_busy": False,
            "pending_time_rule_open_count": 0,
            "pending_time_rule_close_count": 0,
            "pending_time_rule_closes": {},
            "next_time_rule_close_retry": None,
            "time_rule_conflicts": [],
            "time_rule_conflict_count": 0,
            "last_manual_group_command": None,
            "last_manual_cover_command": None,
            "active_weather_protection": None,
            "wind_speed": None,
            "rain_active": None,
            "heat_risk": 0,
            "sun_load": 0,
            "direct_sun": False,
            "direct_sun_by_orientation": {},
            "sun_incidence_by_orientation": {},
            "effective_position_settings": {},
            "desired_positions": {},
            "commanded_positions": {},
            "actual_positions": {},
            "commanded_tilt_positions": {},
            "actual_tilt_positions": {},
            "manual_overrides": {},
            "manual_override_details": {},
            "last_manual_override_event": None,
            "time_rule_manual_releases": [],
            "pending_time_rule_opens": {},
            "contacts": {
                "overall": "none",
                "by_cover": {},
                "by_contact": {},
                "open_covers": [],
                "tilted_covers": [],
                "unknown_covers": [],
                "closed_covers": [],
                "unassigned_covers": [],
                "pending_night_close_covers": [],
                "night_close_delay_seconds": _TIME_RULE_CLOSE_CONTACT_DELAY_SECONDS,
            },
            "last_time_rule_event": None,
            "triggered_time_rules": [],
            "time_rule_states": [],
            "room_temperature": None,
            "outside_temperature": None,
            "forecast_max": None,
            "forecast_updated": None,
            "forecast_age_minutes": None,
            "forecast_stale": False,
            "forecast_type": None,
            "temperature_trend": 0.0,
            "weather_condition": None,
            "weather_factor": 0.0,
            "is_workday": None,
            "workday_data_ready": True,
            "sun_azimuth": None,
            "sun_elevation": None,
            "sun_above_horizon": False,
            "dynamic_daylight": False,
            "sun_entity": None,
            "facade_azimuths": {},
            "last_evaluation": None,
        }
        self._forecast: list[dict[str, Any]] = []
        self._forecast_updated: datetime | None = None
        self._forecast_type: str | None = None
        self._forecast_source: str | None = None
        self._last_move: dict[str, datetime] = {}
        self._last_known_positions: dict[str, int] = {}
        self._last_known_tilt_positions: dict[str, int] = {}
        self._last_command: dict[str, tuple[int, datetime]] = {}
        self._pending_command_targets: dict[str, tuple[int, datetime]] = {}
        self._command_contexts: dict[str, datetime] = {}
        self._command_context_covers: dict[str, str] = {}
        self._manual_detection_suppressed_until: dict[str, datetime] = {}
        self._manual_overrides: dict[str, datetime] = {}
        self._manual_override_details: dict[str, dict[str, Any]] = {}
        self._temperature_samples: deque[tuple[datetime, float]] = deque(maxlen=48)
        self._previous_level: dict[str, str] = {}
        self._unsubscribers: list[Callable[[], None]] = []
        self._debounce_cancel: Callable[[], None] | None = None
        self._command_retry_cancel: Callable[[], None] | None = None
        self._command_retry_at: datetime | None = None
        self._command_retry_attempts = 0
        self._transient_command_failure = False
        self._provider_command_attempted = False
        self._provider_command_succeeded = False
        self._evaluation_lock = asyncio.Lock()
        self._evaluation_pending = False
        self._evaluation_force = False
        self._input_revision = 0
        self._manual_command_revision = 0
        self._started = False
        self._prepared = False
        self._manual_detection_ready = False
        self._last_time_rule_check: datetime | None = None
        self._startup_time_rule_reconciliation = False
        self._workday_data_ready: bool | None = None
        self._availability_reconciliation_covers: set[str] = set()
        self._executed_time_rule_occurrences: set[str] = set()
        self._time_rule_manual_releases: set[str] = set()
        self._pending_time_rule_opens: dict[str, datetime] = {}
        self._pending_time_rule_closes: set[str] = set()
        self._pending_time_rule_close_ready_at: dict[str, datetime] = {}
        self._time_rule_close_retry_cancel: Callable[[], None] | None = None
        self._time_rule_close_retry_at: datetime | None = None
        self._scheduled_close_covers: set[str] = set()
        self._last_tilt_command: dict[str, tuple[int, datetime]] = {}
        self._pending_tilt_targets: dict[str, tuple[int, datetime]] = {}
        self._last_stop_attempt: dict[str, datetime] = {}
        self._last_command_origin: dict[str, tuple[str, datetime]] = {}
        self._decision_history = DecisionHistory(max_entries=100)
        self._active_weather_protection: str | None = None
        self._command_queue = get_command_queue(hass, entry.entry_id)
        self._weather = WeatherRuntime(hass, lambda: self.config)
        self._provider_failures = 0
        self._provider_health_by_cover: dict[str, dict[str, Any]] = {}
        self._override_save_lock = asyncio.Lock()
        self._override_revision = 0
        self._override_expiry_cancel: Callable[[], None] | None = None
        self._override_store = Store(
            hass,
            1,
            f"{DOMAIN}.{entry.entry_id}.manual_overrides",
            atomic_writes=True,
        )
        self._control_state_lock = asyncio.Lock()
        self._last_control_state_save: datetime | None = None
        self._mode_state_loaded = False
        self._enabled_state_loaded = False
        self._control_store = Store(
            hass,
            1,
            f"{DOMAIN}.{entry.entry_id}.control_state",
            atomic_writes=True,
        )

    @property
    def config(self) -> dict[str, Any]:
        """Return effective building and independently stored room settings.

        Central values with room equivalents are templates only. They are
        copied into room options when saved globally; every controller then
        executes only the values stored in its own room entry.
        """
        result = dict(DEFAULTS)
        room_config = dict(self.entry.data)
        room_config.update(self.entry.options)

        central_config: dict[str, Any] = {}
        for item in self.hass.config_entries.async_entries(DOMAIN):
            if (
                str(item.data.get(CONF_ENTRY_TYPE) or "") != ENTRY_TYPE_GLOBAL
                or item.disabled_by is not None
            ):
                continue
            central_config.update(item.data)
            central_config.update(item.options)
            break

        # Shared building settings always come from the central entry. Position
        # templates are resolved separately and never continuously override an
        # explicitly stored room value.
        # Only keys defined as genuinely building-wide settings may flow from
        # the central entry into a room controller. Older migrated entries can
        # still contain room-scoped values (covers, contacts, room sensors or
        # room rules). Copying every key here allowed one room to react to a
        # contact that belonged to another room.
        shared_keys = set(GLOBAL_DEFAULTS)
        for key in shared_keys:
            if key in central_config:
                result[key] = central_config[key]
        result.update(room_config)

        raw_values = central_config.get(CONF_GLOBAL_POSITION_VALUES)
        global_values = raw_values if isinstance(raw_values, dict) else {}
        for key in POSITION_SETTING_KEYS:
            if key in room_config:
                continue
            try:
                global_value = int(global_values.get(key, POSITION_DEFAULTS[key]))
            except (TypeError, ValueError):
                global_value = int(POSITION_DEFAULTS[key])
            result[key] = max(0, min(100, global_value))
        return result

    @property
    def room_name(self) -> str:
        """Return room name."""
        return str(self.config.get(CONF_ROOM_NAME, self.entry.title))

    @property
    def signal(self) -> str:
        """Return dispatcher signal."""
        return SIGNAL_UPDATE.format(entry_id=self.entry.entry_id)

    @property
    def coordinator(self) -> SmartShadingDataCoordinator | None:
        """Return the integration-wide shared data coordinator."""
        runtime = self.hass.data.get(DOMAIN, {})
        coordinator = runtime.get(COORDINATOR_KEY) if isinstance(runtime, dict) else None
        return coordinator if isinstance(coordinator, SmartShadingDataCoordinator) else None

    @property
    def started(self) -> bool:
        """Return whether runtime listeners and evaluation are active."""
        return self._started

    @property
    def mode_state_loaded(self) -> bool:
        """Return whether the operating mode was restored or initialized."""
        return self._mode_state_loaded

    @property
    def enabled_state_loaded(self) -> bool:
        """Return whether the automation switch state was restored or initialized."""
        return self._enabled_state_loaded

    def mark_mode_state_loaded(self) -> None:
        """Mark the operating mode as initialized by its entity restore path."""
        self._mode_state_loaded = True

    def mark_enabled_state_loaded(self) -> None:
        """Mark the automation switch state as initialized by its entity restore path."""
        self._enabled_state_loaded = True

    @property
    def covers_by_orientation(self) -> dict[str, list[str]]:
        """Return configured covers grouped by facade orientation."""
        config = self.config
        return {
            orientation: [str(item) for item in as_list(config.get(key)) if item]
            for orientation, key in _ORIENTATION_CONFIG.items()
        }

    @property
    def all_covers(self) -> list[str]:
        """Return all configured covers without duplicates."""
        return list(dict.fromkeys(
            cover
            for covers in self.covers_by_orientation.values()
            for cover in covers
        ))

    def _watched_entities(self) -> list[str]:
        config = self.config
        entities = list(self.all_covers)
        for key in (
            CONF_ROOM_TEMP_SENSOR,
            CONF_OUTSIDE_TEMP_SENSOR,
            CONF_WEATHER_ENTITY,
            CONF_WORKDAY_ENTITY,
            CONF_IRRADIANCE_SENSOR,
            CONF_ILLUMINANCE_SENSOR,
            CONF_WIND_SENSOR,
            CONF_RAIN_SENSOR,
        ):
            if config.get(key):
                entities.append(str(config[key]))
        contact_mapping = config.get(CONF_COVER_CONTACTS) or {}
        if isinstance(contact_mapping, dict):
            entities.extend(str(value) for value in contact_mapping.values() if value)
        if config.get(CONF_SUN_ENTITY):
            entities.append(str(config[CONF_SUN_ENTITY]))
        return list(dict.fromkeys(entities))

    def _room_repair_entities(self) -> list[str]:
        """Return only entities owned by this room for room-scoped Repairs."""
        config = self.config
        entities = list(self.all_covers)
        room_temperature = config.get(CONF_ROOM_TEMP_SENSOR)
        if room_temperature:
            entities.append(str(room_temperature))
        contact_mapping = config.get(CONF_COVER_CONTACTS) or {}
        if isinstance(contact_mapping, dict):
            entities.extend(str(value) for value in contact_mapping.values() if value)
        return list(dict.fromkeys(entities))

    def _create_entry_task(self, coroutine: Any, name: str) -> asyncio.Task[Any]:
        """Create a task owned and cancelled by this room Config Entry."""
        return self.entry.async_create_task(
            self.hass,
            coroutine,
            name=f"Smart Shading Control {self.entry.entry_id}: {name}",
        )

    async def async_prepare(self) -> None:
        """Restore every restart-relevant controller and manual state."""
        if self._prepared:
            return
        await self._async_restore_control_state()
        await self._async_restore_manual_overrides()
        self._prepared = True

    async def async_start(self) -> None:
        """Start listeners and initial evaluation."""
        if self._started:
            return
        await self.async_prepare()
        self._started = True
        self._schedule_manual_override_expiry()
        self._schedule_time_rule_close_retry()
        if self._command_retry_at is not None:
            self._schedule_command_retry()
        watched = self._watched_entities()
        if watched:
            self._unsubscribers.append(
                async_track_state_change_event(self.hass, watched, self._handle_state_change)
            )
        # Availability edges are filtered explicitly in the state callback and
        # persisted SSC command markers identify our own feedback. Enable
        # manual detection as soon as the listener exists so a real wall-switch
        # action cannot disappear while the shared coordinator is still
        # awaiting its first provider refresh.
        self._manual_detection_ready = True
        if self.coordinator is not None:
            self._unsubscribers.append(
                self.coordinator.async_add_listener(self.async_request_evaluation)
            )
        self._unsubscribers.append(
            self._command_queue.async_add_listener(
                self._handle_command_queue_update
            )
        )
        interval = max(1, int(self.config[CONF_EVALUATION_INTERVAL]))
        self._unsubscribers.append(
            async_track_time_interval(
                self.hass,
                self._handle_interval,
                timedelta(minutes=interval),
            )
        )
        # Temporary manual overrides always end at the next local day change.
        # Register this listener independently of time rules so midnight restores
        # normal integration control in every configured room.
        self._unsubscribers.append(
            async_track_time_change(
                self.hass,
                self._handle_day_change,
                hour=0,
                minute=0,
                second=0,
            )
        )
        # Event rules need minute boundary checks. Rooms without any rules use
        # only the configured evaluation interval and avoid a redundant second
        # periodic evaluation.
        if as_list(self.config.get(CONF_TIME_RULES)):
            self._unsubscribers.append(
                async_track_time_change(
                    self.hass,
                    self._handle_time_rule_tick,
                    second=0,
                )
            )
        # During a full Home Assistant restart, dependent entity platforms may
        # still be loading while config entries are set up. Running the first
        # evaluation at that point creates false Repairs issues and can make a
        # transient provider state look like a permanent configuration fault.
        # Wait for EVENT_HOMEASSISTANT_STARTED; reloads performed while HA is
        # already fully running continue to evaluate immediately.
        if self.hass.state is CoreState.running:
            await self._async_initial_evaluation()
        else:
            self._unsubscribers.append(
                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED,
                    self._handle_homeassistant_started,
                )
            )

    async def _async_initial_evaluation(self) -> None:
        """Refresh shared inputs and evaluate after Home Assistant is ready."""
        if not self._started:
            return
        # Give RestoreEntity callbacks queued by platform setup one event-loop
        # turn to seed the controller on the first upgrade without a store.
        await asyncio.sleep(0)
        coordinator = self.coordinator
        if coordinator is not None:
            await coordinator.async_ensure_ready()
        if self._started:
            # Cover availability transitions are filtered explicitly in the
            # state-change handler. Enable physical/manual movement detection
            # before the first evaluation so a wall-switch action cannot fall
            # into a blanket startup grace period.
            self._manual_detection_ready = True
            self._reconcile_preloaded_cover_positions()
            try:
                # The forced evaluation runs after the configured startup
                # override policy has been applied. It immediately processes the
                # currently valid automatic, time-rule and safety decision.
                self._startup_time_rule_reconciliation = True
                await self.async_evaluate(force=True)
            finally:
                self._startup_time_rule_reconciliation = False
                await self.async_save_control_state()

    @callback
    def _reconcile_preloaded_cover_positions(self) -> None:
        """Protect material offline movements already visible at startup.

        A provider can publish its recovered state before this Config Entry has
        registered its listener. Compare that already-loaded state with the
        persisted per-cover baseline so the absence of a recovery event cannot
        turn an offline wall-switch action into an immediate automatic command.
        The normal recovery classifier also recognizes bounded pending SSC
        targets that completed while Home Assistant was stopped.
        """
        for entity_id in self.all_covers:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
                continue
            previous_position = self._last_known_positions.get(entity_id)
            previous_tilt_position = self._last_known_tilt_positions.get(entity_id)
            current_position = self._position_from_state(state)
            current_tilt_position = self._tilt_position_from_state(state)
            material_position_change = bool(
                previous_position is not None
                and current_position is not None
                and abs(current_position - previous_position)
                >= _MANUAL_POSITION_CHANGE_THRESHOLD
            )
            material_tilt_change = bool(
                previous_tilt_position is not None
                and current_tilt_position is not None
                and abs(current_tilt_position - previous_tilt_position)
                >= _MANUAL_POSITION_CHANGE_THRESHOLD
            )
            if material_position_change or material_tilt_change:
                self._handle_cover_recovery(entity_id, None, state)

    async def _handle_homeassistant_started(self, _event: Event) -> None:
        """Run the initial evaluation only after all integrations had a load chance."""
        await self._async_initial_evaluation()

    async def async_stop(self) -> None:
        """Stop listeners and wait for an in-flight evaluation to finish."""
        # Capture the last state while listeners/manual detection still own a
        # coherent snapshot. If an evaluation currently holds the lock, state
        # changes can arrive during the wait below after ``_started`` is false;
        # reading HA state only after that wait would silently bless such an
        # unclassified wall movement as the new restart baseline.
        shutdown_positions: dict[str, int] = {}
        shutdown_tilt_positions: dict[str, int] = {}
        if self._prepared:
            for entity_id in self.all_covers:
                state = self.hass.states.get(entity_id)
                if state is None or state.state in {
                    STATE_UNKNOWN,
                    STATE_UNAVAILABLE,
                }:
                    continue
                position = self._position_from_state(state)
                if position is not None:
                    shutdown_positions[entity_id] = position
                tilt_position = self._tilt_position_from_state(state)
                if tilt_position is not None:
                    shutdown_tilt_positions[entity_id] = tilt_position
        self._started = False
        self._manual_detection_ready = False
        if self._debounce_cancel:
            self._debounce_cancel()
            self._debounce_cancel = None
        if self._command_retry_cancel:
            self._command_retry_cancel()
            self._command_retry_cancel = None
        if self._time_rule_close_retry_cancel:
            self._time_rule_close_retry_cancel()
            self._time_rule_close_retry_cancel = None
        if self._override_expiry_cancel:
            self._override_expiry_cancel()
            self._override_expiry_cancel = None
        self._time_rule_close_retry_at = None
        self.data["next_provider_retry"] = None
        self.data["next_time_rule_close_retry"] = None
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        async with self._evaluation_lock:
            self._evaluation_pending = False
            self._evaluation_force = False
        if not self._prepared:
            # A failed Store restore must never be followed by writing the
            # controller's empty/default dictionaries over the only persistent
            # safety state during partial-setup cleanup.
            return
        self._last_known_positions.update(shutdown_positions)
        self._last_known_tilt_positions.update(shutdown_tilt_positions)
        await self.async_save_control_state()
        self._override_revision += 1
        await self._async_save_manual_overrides(self._override_revision)

    @callback
    def _handle_state_change(self, event: Event) -> None:
        """Handle relevant state changes and detect manual cover operation."""
        entity_id = event.data.get("entity_id")
        old_state: State | None = event.data.get("old_state")
        new_state: State | None = event.data.get("new_state")
        if not self._started or not entity_id:
            return

        is_cover = entity_id in self.all_covers

        # Removing an assigned contact from the state machine is equivalent to
        # an immediate transition to unknown. Do not wait for the periodic room
        # evaluation before applying the configured contact fail-safe.
        if new_state is None:
            if self._is_configured_contact(entity_id):
                old_kind = classify_contact_state(
                    old_state.state if old_state is not None else None,
                    old_state.attributes if old_state is not None else None,
                )
                if (
                    old_kind != CONTACT_UNKNOWN
                    and (
                        self._manual_detection_ready
                        or self.hass.state is CoreState.running
                    )
                ):
                    self._create_entry_task(
                        self._async_enforce_contact_safety(entity_id),
                        "contact safety",
                    )
            self._schedule_evaluation(invalidate=True)
            return

        if is_cover:
            old_unavailable = old_state is None or old_state.state in {
                STATE_UNKNOWN,
                STATE_UNAVAILABLE,
            }
            new_unavailable = new_state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}
            if old_unavailable or new_unavailable:
                if new_unavailable:
                    # Retain the last reliable per-cover position. If the
                    # provider later returns with a materially different value,
                    # that single recovery event may be the only evidence of a
                    # wall-switch action performed while it was unavailable.
                    previous_position = self._position_from_state(old_state)
                    previous_tilt_position = self._tilt_position_from_state(old_state)
                    position_state_changed = False
                    if (
                        not old_unavailable
                        and previous_position is not None
                        and self._last_known_positions.get(entity_id)
                        != previous_position
                    ):
                        self._last_known_positions[entity_id] = previous_position
                        position_state_changed = True
                    if (
                        not old_unavailable
                        and previous_tilt_position is not None
                        and self._last_known_tilt_positions.get(entity_id)
                        != previous_tilt_position
                    ):
                        self._last_known_tilt_positions[entity_id] = (
                            previous_tilt_position
                        )
                        position_state_changed = True
                    if position_state_changed:
                        self._create_entry_task(
                            self.async_save_control_state(),
                            "persist positions before provider loss",
                        )
                    self._schedule_evaluation(invalidate=True)
                    return

                command_related_event = self._handle_cover_recovery(
                    entity_id,
                    old_state,
                    new_state,
                )
                self._schedule_evaluation(invalidate=not command_related_event)
                return

        command_related_event = False
        if (
            is_cover
            and old_state is not None
            and self._manual_detection_ready
        ):
            command_related_event = self._detect_manual_override(
                entity_id, old_state, new_state
            )
        elif self._is_configured_contact(entity_id):
            old_kind = classify_contact_state(
                old_state.state if old_state is not None else None,
                old_state.attributes if old_state is not None else None,
            )
            new_kind = classify_contact_state(new_state.state, new_state.attributes)
            reliable_transition = (
                old_kind == CONTACT_CLOSED
                and new_kind in {CONTACT_OPEN, CONTACT_TILTED}
            ) or (
                old_kind in {CONTACT_OPEN, CONTACT_TILTED}
                and new_kind == CONTACT_CLOSED
            )
            availability_loss = (
                old_kind != CONTACT_UNKNOWN and new_kind == CONTACT_UNKNOWN
            )
            if (
                (reliable_transition or availability_loss)
                and (
                    self._manual_detection_ready
                    or self.hass.state is CoreState.running
                )
            ):
                self._create_entry_task(
                    self._async_enforce_contact_safety(entity_id),
                    "contact safety",
                )

        own_command_event = command_related_event or bool(
            new_state.context
            and (
                new_state.context.id in self._command_contexts
                or getattr(new_state.context, "parent_id", None)
                in self._command_contexts
            )
        )
        self._schedule_evaluation(invalidate=not own_command_event)

    @callback
    def _handle_interval(self, now: datetime) -> None:
        """Run periodic evaluation."""
        if self._started:
            self._create_entry_task(self.async_evaluate(), "periodic evaluation")

    @callback
    def _handle_time_rule_tick(self, now: datetime) -> None:
        """Evaluate internal time rules at minute boundaries."""
        if self._started:
            self._schedule_evaluation(invalidate=True)

    @callback
    def _handle_day_change(self, now: datetime) -> None:
        """Clear manual overrides at local midnight and reevaluate safely.

        Midnight itself must never be interpreted as a reason to open shutters.
        The forced evaluation applies a triggered time-rule event or a safety action,
        while the dynamic solar controller now holds positions during darkness.
        """
        if not self._started:
            return
        self._input_revision += 1
        manual_state_changed = bool(
            self._manual_overrides or self._time_rule_manual_releases
        )
        if manual_state_changed:
            _LOGGER.debug(
                "Clearing %s manual override(s) and %s manual release(s) for %s "
                "at local day change",
                len(self._manual_overrides),
                len(self._time_rule_manual_releases),
                self.room_name,
            )
            self._manual_overrides.clear()
            self._manual_override_details.clear()
            self.data["manual_overrides"] = {}
            self.data["manual_override_details"] = {}
            self._time_rule_manual_releases.clear()
            self._schedule_override_save()
            self._create_entry_task(
                self.async_save_control_state(), "persist midnight reset"
            )
        self._create_entry_task(
            self.async_evaluate(force=True), "midnight evaluation"
        )

    @callback
    def _schedule_command_retry(self) -> None:
        """Schedule an adaptive retry with exponential backoff and jitter."""
        if not self._started or self._command_retry_cancel is not None:
            return
        now = dt_util.utcnow()
        if self._command_retry_at is not None:
            delay = (self._command_retry_at - now).total_seconds()
            if delay <= 0:
                self._command_retry_at = None
                return
        else:
            if self._command_retry_attempts >= _MAX_COMMAND_RETRIES:
                return
            base_delay = _COMMAND_RETRY_DELAYS[self._command_retry_attempts]
            self._command_retry_attempts += 1
            delay = max(1.0, base_delay * random.uniform(0.85, 1.15))
            self._command_retry_at = now + timedelta(seconds=delay)
        self.data["next_provider_retry"] = self._command_retry_at.isoformat()
        self._command_retry_cancel = async_call_later(
            self.hass,
            delay,
            self._handle_command_retry,
        )
        self._create_entry_task(
            self.async_save_control_state(), "persist provider retry"
        )
        self._publish()

    async def _handle_command_retry(self, _now: datetime) -> None:
        """Retry the complete room decision after the provider had time to recover."""
        self._command_retry_cancel = None
        self._command_retry_at = None
        self.data["next_provider_retry"] = None
        await self.async_save_control_state()
        if self._started:
            await self.async_evaluate(force=True)

    @callback
    def _schedule_time_rule_close_retry(self) -> None:
        """Schedule the earliest delayed night-close reevaluation."""
        if not self._started:
            return
        now = dt_util.utcnow()
        future = [
            retry_at
            for retry_at in self._pending_time_rule_close_ready_at.values()
            if retry_at > now
        ]
        next_retry = min(future, default=None)
        if next_retry == self._time_rule_close_retry_at:
            return
        if self._time_rule_close_retry_cancel is not None:
            self._time_rule_close_retry_cancel()
            self._time_rule_close_retry_cancel = None
        self._time_rule_close_retry_at = next_retry
        self.data["next_time_rule_close_retry"] = (
            next_retry.isoformat() if next_retry is not None else None
        )
        if next_retry is None:
            return
        delay = max(0.0, (next_retry - now).total_seconds())
        self._time_rule_close_retry_cancel = async_call_later(
            self.hass, delay, self._handle_time_rule_close_retry
        )

    async def _handle_time_rule_close_retry(self, _now: datetime) -> None:
        """Reevaluate a night close after the contact stayed closed."""
        self._time_rule_close_retry_cancel = None
        self._time_rule_close_retry_at = None
        self.data["next_time_rule_close_retry"] = None
        if self._started:
            self._input_revision += 1
            await self.async_evaluate(force=True)

    def _clear_pending_time_rule_closes(self) -> bool:
        """Clear all contact-blocked night-close state."""
        changed = bool(
            self._pending_time_rule_closes
            or self._pending_time_rule_close_ready_at
        )
        self._pending_time_rule_closes.clear()
        self._pending_time_rule_close_ready_at.clear()
        self._schedule_time_rule_close_retry()
        return changed

    def _clear_pending_time_rules_for_covers(
        self, covers: list[str] | tuple[str, ...] | set[str]
    ) -> bool:
        """Clear pending schedule retries only for the selected covers."""
        changed = False
        for entity_id in covers:
            if self._pending_time_rule_opens.pop(entity_id, None) is not None:
                changed = True
            if entity_id in self._pending_time_rule_closes:
                self._pending_time_rule_closes.discard(entity_id)
                changed = True
            if self._pending_time_rule_close_ready_at.pop(entity_id, None) is not None:
                changed = True
        self._schedule_time_rule_close_retry()
        return changed

    def _sync_pending_time_rule_data(self) -> None:
        """Synchronize persisted pending schedule state with diagnostics."""
        self.data["pending_time_rule_opens"] = {
            entity: expiry.isoformat()
            for entity, expiry in self._pending_time_rule_opens.items()
        }
        self.data["pending_time_rule_closes"] = {
            entity: {
                "retry_at": (
                    self._pending_time_rule_close_ready_at[entity].isoformat()
                    if entity in self._pending_time_rule_close_ready_at
                    else None
                ),
                "contact_state": self._contact_state_for_cover(entity),
            }
            for entity in sorted(self._pending_time_rule_closes)
        }
        self.data["pending_time_rule_open_count"] = len(
            self._pending_time_rule_opens
        )
        self.data["pending_time_rule_close_count"] = len(
            self._pending_time_rule_closes
        )

    @callback
    def _handle_command_queue_update(self) -> None:
        """Publish queue depth and active state without forcing a decision."""
        snapshot = self._command_queue.snapshot()
        self.data["command_queue"] = snapshot
        self.data["command_queue_depth"] = int(snapshot.get("depth", 0))
        self.data["command_queue_busy"] = bool(snapshot.get("busy"))
        if self._started:
            self._publish()

    @callback
    def async_request_evaluation(self) -> None:
        """Invalidate the current input snapshot and debounce a reevaluation."""
        self._schedule_evaluation(invalidate=True)

    @callback
    def _schedule_evaluation(self, *, invalidate: bool) -> None:
        """Debounce input bursts and optionally invalidate an in-flight plan."""
        if not self._started:
            return
        if invalidate:
            self._input_revision += 1
        # During a full Home Assistant startup, collect input changes but let the
        # single forced post-start evaluation consume them. This avoids an early
        # partial evaluation before all provider integrations have loaded.
        if self.hass.state is not CoreState.running:
            return
        if self._debounce_cancel:
            self._debounce_cancel()
        self._debounce_cancel = async_call_later(
            self.hass,
            1.5,
            self._debounced_evaluation,
        )

    async def _debounced_evaluation(self, _now: datetime) -> None:
        self._debounce_cancel = None
        if self._started:
            await self.async_evaluate()

    @staticmethod
    def _bounded_target_feedback(
        previous: int | None,
        current: int | None,
        target: int,
    ) -> bool:
        """Return whether feedback stays inside the corridor toward a target."""
        if current is None:
            return False
        if abs(current - target) <= POSITION_TOLERANCE:
            return True
        if previous is None:
            return False
        if target > previous + POSITION_TOLERANCE:
            return (
                previous - POSITION_TOLERANCE
                <= current
                <= target + POSITION_TOLERANCE
            )
        if target < previous - POSITION_TOLERANCE:
            return (
                target - POSITION_TOLERANCE
                <= current
                <= previous + POSITION_TOLERANCE
            )
        return abs(current - target) <= POSITION_TOLERANCE

    def _activate_manual_override(
        self,
        entity_id: str,
        old: State,
        new: State,
        old_position: int | None,
        new_position: int | None,
        now: datetime,
        *,
        trigger: str,
        old_tilt_position: int | None = None,
        new_tilt_position: int | None = None,
        preserve_existing_expiry: bool = False,
    ) -> None:
        """Create one evidenced manual override and retain its diagnostic cause."""
        existing_expiry = self._manual_overrides.get(entity_id)
        expiry = (
            existing_expiry
            if preserve_existing_expiry
            and existing_expiry is not None
            and existing_expiry > now
            else self._manual_override_expiry(
                now, max(0, int(self.config[CONF_MANUAL_OVERRIDE_MINUTES]))
            )
        )
        if expiry is None:
            return

        manual_opening = (
            (
                old_position is not None
                and new_position is not None
                and new_position > old_position
            )
            or new.state in {"opening", "open"}
        )
        contact_blocks_night_close = (
            entity_id in self._scheduled_close_covers
            and self._contact_state_for_cover(entity_id)
            in {CONTACT_OPEN, CONTACT_TILTED, CONTACT_UNKNOWN}
        )
        if (
            manual_opening or contact_blocks_night_close
        ) and entity_id not in self._time_rule_manual_releases:
            self._time_rule_manual_releases.add(entity_id)
            self._pending_time_rule_closes.discard(entity_id)
            self._pending_time_rule_close_ready_at.pop(entity_id, None)
            self._schedule_time_rule_close_retry()
            self._create_entry_task(
                self.async_save_control_state(), "persist manual release"
            )

        context = new.context
        details = {
            "cover_entity_id": entity_id,
            "detected_at": now.isoformat(),
            "expires_at": expiry.isoformat(),
            "trigger": trigger,
            "old_state": old.state,
            "new_state": new.state,
            "old_position": old_position,
            "new_position": new_position,
            "old_tilt_position": old_tilt_position,
            "new_tilt_position": new_tilt_position,
            "user_context": bool(context and getattr(context, "user_id", None)),
            "parent_context": bool(context and getattr(context, "parent_id", None)),
        }
        self._clear_command_markers_for_cover(entity_id, include_tilt=True)
        self._manual_overrides[entity_id] = expiry
        self._manual_override_details[entity_id] = details
        self.data["manual_overrides"] = {
            cover: override_expiry.isoformat()
            for cover, override_expiry in self._manual_overrides.items()
        }
        self.data["manual_override_details"] = {
            cover: dict(value)
            for cover, value in self._manual_override_details.items()
            if cover in self._manual_overrides
        }
        self.data["last_manual_override_event"] = dict(details)
        self._schedule_override_save()
        self._create_entry_task(
            self.async_save_control_state(), "persist manual override"
        )
        _LOGGER.debug(
            "Manual override detected for %s (%s: %s/%s -> %s/%s)",
            entity_id,
            trigger,
            old.state,
            old_position,
            new.state,
            new_position,
        )

    def _handle_cover_recovery(
        self,
        entity_id: str,
        old_state: State | None,
        new_state: State,
    ) -> bool:
        """Protect an offline movement or recognize fresh SSC feedback.

        Return true only when the recovery can be attributed to a recent SSC
        command. A material unexplained delta is conservatively treated as a
        manual movement because providers commonly publish no second event
        after their sole unavailable-to-available recovery update.
        """
        # A fixed-duration startup OPEN retry may already have elapsed during a
        # longer provider outage. Retain this recovery edge independently so the
        # next coherent evaluation can reconcile the current OPEN rule state for
        # this cover exactly once.
        self._availability_reconciliation_covers.add(entity_id)
        now = dt_util.utcnow()
        self._purge_expired(now)
        previous_position = self._last_known_positions.get(entity_id)
        previous_tilt_position = self._last_known_tilt_positions.get(entity_id)
        new_position = self._position_from_state(new_state)
        new_tilt_position = self._tilt_position_from_state(new_state)
        context = new_state.context
        own_context = bool(
            context
            and (
                context.id in self._command_contexts
                or getattr(context, "parent_id", None) in self._command_contexts
            )
        )
        suppressed = (
            self._manual_detection_suppressed_until.get(entity_id, now) > now
        )
        vertical_intent = self._pending_command_targets.get(entity_id)
        if vertical_intent is None:
            last_command = self._last_command.get(entity_id)
            if (
                last_command is not None
                and (now - last_command[1]).total_seconds()
                <= COMMAND_GRACE_SECONDS
            ):
                vertical_intent = (last_command[0], now)
        tilt_intent = self._pending_tilt_targets.get(entity_id)
        if tilt_intent is None:
            last_tilt_command = self._last_tilt_command.get(entity_id)
            if (
                last_tilt_command is not None
                and (now - last_tilt_command[1]).total_seconds()
                <= COMMAND_GRACE_SECONDS
            ):
                tilt_intent = (last_tilt_command[0], now)
        follows_vertical_command = bool(
            vertical_intent is not None
            and self._bounded_target_feedback(
                previous_position,
                new_position,
                vertical_intent[0],
            )
        )
        follows_tilt_command = bool(
            tilt_intent is not None
            and self._bounded_target_feedback(
                previous_tilt_position,
                new_tilt_position,
                tilt_intent[0],
            )
        )

        external_context = bool(
            context
            and (
                getattr(context, "user_id", None)
                or getattr(context, "parent_id", None)
            )
        )
        material_position_change = bool(
            previous_position is not None
            and new_position is not None
            and abs(new_position - previous_position)
            >= _MANUAL_POSITION_CHANGE_THRESHOLD
        )
        material_tilt_change = bool(
            previous_tilt_position is not None
            and new_tilt_position is not None
            and abs(new_tilt_position - previous_tilt_position)
            >= _MANUAL_POSITION_CHANGE_THRESHOLD
        )
        state_changed = bool(
            new_position is not None
            and self._last_known_positions.get(entity_id) != new_position
        )
        if new_position is not None:
            self._last_known_positions[entity_id] = new_position
        if (
            new_tilt_position is not None
            and self._last_known_tilt_positions.get(entity_id) != new_tilt_position
        ):
            state_changed = True
        if new_tilt_position is not None:
            self._last_known_tilt_positions[entity_id] = new_tilt_position

        pending_target_changed = False
        if (
            vertical_intent is not None
            and new_position is not None
            and abs(new_position - vertical_intent[0]) <= POSITION_TOLERANCE
            and self._pending_command_targets.pop(entity_id, None) is not None
        ):
            pending_target_changed = True
        if (
            tilt_intent is not None
            and new_tilt_position is not None
            and abs(new_tilt_position - tilt_intent[0]) <= POSITION_TOLERANCE
            and self._pending_tilt_targets.pop(entity_id, None) is not None
        ):
            pending_target_changed = True

        if (
            self._manual_detection_ready
            and not own_context
            and not suppressed
            and (
                external_context
                or (
                    material_position_change
                    and not follows_vertical_command
                )
                or (material_tilt_change and not follows_tilt_command)
            )
        ):
            self._activate_manual_override(
                entity_id,
                old_state or new_state,
                new_state,
                previous_position,
                new_position,
                now,
                trigger=(
                    "recovery_external_context"
                    if external_context
                    else (
                        "recovery_tilt_position_change"
                        if material_tilt_change and not follows_tilt_command
                        else "recovery_position_change"
                    )
                ),
                old_tilt_position=previous_tilt_position,
                new_tilt_position=new_tilt_position,
                preserve_existing_expiry=True,
            )
            return False

        if state_changed or pending_target_changed:
            self._create_entry_task(
                self.async_save_control_state(),
                "persist recovered provider positions",
            )
        return bool(
            own_context
            or suppressed
            or follows_vertical_command
            or follows_tilt_command
        )

    def _detect_manual_override(self, entity_id: str, old: State, new: State) -> bool:
        """Detect evidenced manual movement and identify provider command events."""
        now = dt_util.utcnow()
        self._purge_expired(now)

        # Contexts created by Smart Shading Control itself always win first.
        # This is the reliable marker for provider state changes caused by one
        # of our own commands.
        if new.context and (
            new.context.id in self._command_contexts
            or getattr(new.context, "parent_id", None) in self._command_contexts
        ):
            return True
        if old.state in {STATE_UNKNOWN, STATE_UNAVAILABLE} or new.state in {
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        }:
            return True

        old_position = self._position_from_state(old)
        new_position = self._position_from_state(new)
        old_tilt_position = self._tilt_position_from_state(old)
        new_tilt_position = self._tilt_position_from_state(new)
        material_tilt_change = bool(
            old_tilt_position is not None
            and new_tilt_position is not None
            and abs(new_tilt_position - old_tilt_position)
            >= _MANUAL_POSITION_CHANGE_THRESHOLD
        )
        moving_states = {"opening", "closing"}
        context = new.context
        external_context = bool(
            context
            and (
                getattr(context, "user_id", None)
                or getattr(context, "parent_id", None)
            )
        )

        # An explicitly external HA context is stronger evidence than the
        # heuristic grace markers below. In particular, the first cover of a
        # manual multi-cover operation can still have a recent SSC last-command
        # marker. Previously that marker caused the user action to be mistaken
        # for the tail of the automatic command, so no manual override was set
        # for that cover and a later evaluation moved only it back.
        if external_context:
            trigger = manual_movement_trigger(
                old_state=old.state,
                new_state=new.state,
                old_position=old_position,
                new_position=new_position,
                external_context=True,
                position_threshold=_MANUAL_POSITION_CHANGE_THRESHOLD,
            )
            if trigger is None and material_tilt_change:
                trigger = "external_tilt_position_change"
            if trigger is not None:
                self._activate_manual_override(
                    entity_id,
                    old,
                    new,
                    old_position,
                    new_position,
                    now,
                    trigger=trigger,
                    old_tilt_position=old_tilt_position,
                    new_tilt_position=new_tilt_position,
                )
                return False

        suppressed_until = self._manual_detection_suppressed_until.get(
            entity_id, now
        )
        if suppressed_until > now:
            return True

        pending_state_changed = False
        vertical_intent = self._pending_command_targets.get(entity_id)
        if vertical_intent is None:
            last_command = self._last_command.get(entity_id)
            if (
                last_command is not None
                and (now - last_command[1]).total_seconds()
                <= COMMAND_GRACE_SECONDS
            ):
                vertical_intent = (last_command[0], now)
        vertical_command_feedback = False
        if vertical_intent is not None:
            commanded_target = vertical_intent[0]
            reached_target = (
                new_position is not None
                and abs(new_position - commanded_target) <= POSITION_TOLERANCE
                and new.state not in moving_states
            )
            follows_command = self._bounded_target_feedback(
                old_position,
                new_position,
                commanded_target,
            )
            if follows_command and old_position is not None:
                # A provider update may progress toward our target, but a wall
                # command that passes that target is new intent. The former
                # direction-only check classified e.g. SSC 40→50 followed by a
                # physical 40→80 movement as SSC feedback and left the cover
                # without a manual override.
                if (
                    commanded_target > old_position + POSITION_TOLERANCE
                    and new.state in moving_states
                ):
                    follows_command = follows_command and new.state == "opening"
                elif (
                    commanded_target < old_position - POSITION_TOLERANCE
                    and new.state in moving_states
                ):
                    follows_command = follows_command and new.state == "closing"
            elif (
                not follows_command
                and (old_position is None or new_position is None)
                and new.state in moving_states
            ):
                reference = old_position if old_position is not None else new_position
                if (
                    reference is not None
                    and abs(commanded_target - reference) > POSITION_TOLERANCE
                ):
                    expected_state = (
                        "opening" if commanded_target > reference else "closing"
                    )
                    follows_command = new.state == expected_state

            vertical_command_feedback = reached_target or follows_command
            if (
                new_position is not None
                and abs(new_position - commanded_target) <= POSITION_TOLERANCE
                and self._pending_command_targets.pop(entity_id, None) is not None
            ):
                pending_state_changed = True

        tilt_intent = self._pending_tilt_targets.get(entity_id)
        if tilt_intent is None:
            last_tilt_command = self._last_tilt_command.get(entity_id)
            if (
                last_tilt_command is not None
                and (now - last_tilt_command[1]).total_seconds()
                <= COMMAND_GRACE_SECONDS
            ):
                tilt_intent = (last_tilt_command[0], now)
        tilt_command_feedback = bool(
            tilt_intent is not None
            and self._bounded_target_feedback(
                old_tilt_position,
                new_tilt_position,
                tilt_intent[0],
            )
        )
        if (
            tilt_intent is not None
            and new_tilt_position is not None
            and abs(new_tilt_position - tilt_intent[0]) <= POSITION_TOLERANCE
            and self._pending_tilt_targets.pop(entity_id, None) is not None
        ):
            pending_state_changed = True

        if material_tilt_change and not tilt_command_feedback:
            self._activate_manual_override(
                entity_id,
                old,
                new,
                old_position,
                new_position,
                now,
                trigger="tilt_position_change",
                old_tilt_position=old_tilt_position,
                new_tilt_position=new_tilt_position,
            )
            return False

        trigger = manual_movement_trigger(
            old_state=old.state,
            new_state=new.state,
            old_position=old_position,
            new_position=new_position,
            external_context=external_context,
            position_threshold=_MANUAL_POSITION_CHANGE_THRESHOLD,
        )

        if trigger is not None and not vertical_command_feedback:
            self._activate_manual_override(
                entity_id,
                old,
                new,
                old_position,
                new_position,
                now,
                trigger=trigger,
                old_tilt_position=old_tilt_position,
                new_tilt_position=new_tilt_position,
            )
            return False
        if pending_state_changed:
            self._create_entry_task(
                self.async_save_control_state(),
                "clear reached provider target",
            )
        return vertical_command_feedback or tilt_command_feedback

    def _purge_expired(
        self,
        now: datetime,
        *,
        schedule_persistence: bool = True,
    ) -> None:
        active_overrides = {
            entity: expiry
            for entity, expiry in self._manual_overrides.items()
            if expiry > now
        }
        expired_override_covers = set(self._manual_overrides) - set(active_overrides)
        self._manual_overrides = active_overrides
        self.data["manual_overrides"] = {
            entity: expiry.isoformat()
            for entity, expiry in active_overrides.items()
        }
        self._manual_override_details = {
            entity: details
            for entity, details in self._manual_override_details.items()
            if entity in active_overrides
        }
        self.data["manual_override_details"] = {
            entity: dict(details)
            for entity, details in self._manual_override_details.items()
        }
        expired_releases = expired_override_covers & self._time_rule_manual_releases
        if expired_override_covers and schedule_persistence:
            self._schedule_override_save()
        if expired_releases:
            self._time_rule_manual_releases.difference_update(expired_releases)
            if schedule_persistence:
                self._create_entry_task(
                    self.async_save_control_state(), "purge expired manual state"
                )
        self._command_contexts = {
            context_id: expiry
            for context_id, expiry in self._command_contexts.items()
            if expiry > now
        }
        self._command_context_covers = {
            context_id: entity_id
            for context_id, entity_id in self._command_context_covers.items()
            if context_id in self._command_contexts
        }
        self._manual_detection_suppressed_until = {
            entity_id: expiry
            for entity_id, expiry in self._manual_detection_suppressed_until.items()
            if expiry > now
        }
        self._last_command = {
            entity_id: command
            for entity_id, command in self._last_command.items()
            if now - command[1] <= timedelta(seconds=COMMAND_GRACE_SECONDS)
        }
        self._last_tilt_command = {
            entity_id: command
            for entity_id, command in self._last_tilt_command.items()
            if now - command[1] <= timedelta(seconds=COMMAND_GRACE_SECONDS)
        }
        self._pending_command_targets = {
            entity_id: intent
            for entity_id, intent in self._pending_command_targets.items()
            if intent[1] > now
        }
        self._pending_tilt_targets = {
            entity_id: intent
            for entity_id, intent in self._pending_tilt_targets.items()
            if intent[1] > now
        }
        self._pending_time_rule_opens = {
            entity_id: expiry
            for entity_id, expiry in self._pending_time_rule_opens.items()
            if expiry > now and entity_id in self.all_covers
        }

    @staticmethod
    def _manual_override_expiry(now: datetime, minutes: int) -> datetime | None:
        """Return an override expiry capped at the next local midnight."""
        if minutes <= 0:
            return None
        minutes = min(1440, minutes)
        local_now = dt_util.as_local(now)
        next_local_midnight = datetime.combine(
            local_now.date() + timedelta(days=1),
            time.min,
            tzinfo=local_now.tzinfo,
        )
        return min(
            now + timedelta(minutes=minutes),
            dt_util.as_utc(next_local_midnight),
        )

    def _sync_manual_override_data(self) -> None:
        """Publish per-cover override state from its authoritative dictionaries."""
        self.data["manual_overrides"] = {
            entity: expiry.isoformat()
            for entity, expiry in self._manual_overrides.items()
        }
        self.data["manual_override_details"] = {
            entity: dict(details)
            for entity, details in self._manual_override_details.items()
            if entity in self._manual_overrides
        }

    def _clear_command_markers_for_cover(
        self, entity_id: str, *, include_tilt: bool = False
    ) -> None:
        """Forget stale integration intent owned by one physical cover."""
        self._last_command.pop(entity_id, None)
        self._pending_command_targets.pop(entity_id, None)
        self._last_command_origin.pop(entity_id, None)
        if include_tilt:
            self._last_tilt_command.pop(entity_id, None)
            self._pending_tilt_targets.pop(entity_id, None)
        for context_id, owner in list(self._command_context_covers.items()):
            if owner == entity_id:
                self._command_context_covers.pop(context_id, None)
                self._command_contexts.pop(context_id, None)

    def _set_reason(
        self, status: str, reason_code: str, context: dict[str, Any] | None = None
    ) -> None:
        """Store a stable reason code instead of a hard-coded runtime sentence."""
        self.data.update(
            status=status,
            reason=reason_code,
            reason_code=reason_code,
            reason_context=context or {},
        )

    def _is_configured_contact(self, entity_id: str) -> bool:
        mapping = self.config.get(CONF_COVER_CONTACTS) or {}
        return isinstance(mapping, dict) and entity_id in {
            str(value) for value in mapping.values() if value
        }

    def _contact_state_for_cover(self, cover_entity: str) -> str | None:
        """Return the classified assigned contact state for one cover."""
        mapping = self.config.get(CONF_COVER_CONTACTS) or {}
        if not isinstance(mapping, dict):
            return None
        contact_entity = str(mapping.get(cover_entity) or "").strip()
        if not contact_entity:
            return None
        state = self.hass.states.get(contact_entity)
        return classify_contact_state(
            state.state if state is not None else None,
            state.attributes if state is not None else None,
        )

    def _runtime_storage_state(self) -> dict[str, Any]:
        """Return safety-relevant runtime state using absolute timestamps."""
        return {
            "last_move_at": {
                entity: timestamp.isoformat()
                for entity, timestamp in self._last_move.items()
                if entity in self.all_covers
            },
            "last_known_positions": {
                entity: position
                for entity, position in self._last_known_positions.items()
                if entity in self.all_covers
            },
            "last_known_tilt_positions": {
                entity: position
                for entity, position in self._last_known_tilt_positions.items()
                if entity in self.all_covers
            },
            "last_commands": {
                entity: {"target": target, "issued_at": issued_at.isoformat()}
                for entity, (target, issued_at) in self._last_command.items()
                if entity in self.all_covers
            },
            "pending_command_targets": {
                entity: {"target": target, "expires_at": expires_at.isoformat()}
                for entity, (target, expires_at) in (
                    self._pending_command_targets.items()
                )
                if entity in self.all_covers
            },
            "command_contexts": {
                context_id: expiry.isoformat()
                for context_id, expiry in self._command_contexts.items()
            },
            "command_context_covers": {
                context_id: entity_id
                for context_id, entity_id in self._command_context_covers.items()
                if context_id in self._command_contexts
                and entity_id in self.all_covers
            },
            "manual_detection_suppressed_until": {
                entity: expiry.isoformat()
                for entity, expiry in self._manual_detection_suppressed_until.items()
                if entity in self.all_covers
            },
            "last_command_origins": {
                entity: {"origin": origin, "issued_at": issued_at.isoformat()}
                for entity, (origin, issued_at) in self._last_command_origin.items()
                if entity in self.all_covers
            },
            "last_tilt_commands": {
                entity: {"target": target, "issued_at": issued_at.isoformat()}
                for entity, (target, issued_at) in self._last_tilt_command.items()
                if entity in self.all_covers
            },
            "pending_tilt_targets": {
                entity: {"target": target, "expires_at": expires_at.isoformat()}
                for entity, (target, expires_at) in self._pending_tilt_targets.items()
                if entity in self.all_covers
            },
            "previous_levels": {
                orientation: level
                for orientation, level in self._previous_level.items()
                if orientation in _ORIENTATION_CONFIG
                and level in {"normal", "preventive", "heat", "strong"}
            },
            "temperature_samples": [
                [timestamp.isoformat(), value]
                for timestamp, value in self._temperature_samples
            ],
            "weather_protection": self._weather.storage_state(),
            "provider_retry_at": (
                self._command_retry_at.isoformat()
                if self._command_retry_at is not None
                else None
            ),
            "provider_retry_attempts": self._command_retry_attempts,
            "forecast_cache": {
                "source": self._forecast_source,
                "updated_at": (
                    self._forecast_updated.isoformat()
                    if self._forecast_updated is not None
                    else None
                ),
                "type": self._forecast_type,
                "items": [
                    {"temperature": item.get("temperature")}
                    for item in self._forecast
                    if item.get("temperature") is not None
                ],
            },
        }

    @staticmethod
    def _validate_control_state_safety(
        stored: dict[str, Any],
        *,
        now: datetime,
        covers: list[str],
    ) -> None:
        """Reject malformed persisted fields that could remove a safety hold."""
        configured_covers = set(covers)

        def invalid(field: str) -> None:
            raise ConfigEntryNotReady(
                f"Smart Shading Control runtime field {field!r} is invalid"
            )

        valid_modes = {
            MODE_AUTOMATIC,
            MODE_HEAT_PROTECTION,
            MODE_OPEN,
            MODE_CLOSED,
            MODE_PAUSE,
        }
        if "mode" in stored:
            mode = stored["mode"]
            if not isinstance(mode, str) or mode not in valid_modes:
                invalid("mode")

        if "enabled" in stored:
            enabled = stored["enabled"]
            valid_boolean = isinstance(enabled, bool) or (
                isinstance(enabled, (int, float))
                and not isinstance(enabled, bool)
                and isfinite(float(enabled))
                and enabled in {0, 1}
            )
            if isinstance(enabled, str):
                valid_boolean = enabled.strip().lower() in {
                    "0",
                    "1",
                    "false",
                    "true",
                    "no",
                    "yes",
                    "off",
                    "on",
                    "disabled",
                    "enabled",
                }
            if not valid_boolean:
                invalid("enabled")

        raw_check = stored.get("last_time_rule_check")
        if "last_time_rule_check" in stored and raw_check is not None:
            parsed_check = parse_aware_utc_timestamp(raw_check)
            if parsed_check is None or parsed_check > now:
                invalid("last_time_rule_check")

        for field in (
            "time_rule_manual_releases",
            "scheduled_close_covers",
            "pending_time_rule_closes",
            "executed_time_rule_occurrences",
        ):
            if field not in stored:
                continue
            values = stored[field]
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value for value in values
            ):
                invalid(field)

        for field, max_future in (
            ("pending_time_rule_opens", timedelta(days=1)),
            ("pending_time_rule_close_ready_at", timedelta(minutes=15)),
        ):
            if field not in stored:
                continue
            values = stored[field]
            if not isinstance(values, dict):
                invalid(field)
            for raw_entity, raw_timestamp in values.items():
                if str(raw_entity) not in configured_covers:
                    continue
                timestamp = parse_aware_utc_timestamp(raw_timestamp)
                if timestamp is None or timestamp - now > max_future:
                    invalid(field)

        if "last_move_at" in stored:
            values = stored["last_move_at"]
            if not isinstance(values, dict):
                invalid("last_move_at")
            for raw_entity, raw_timestamp in values.items():
                if str(raw_entity) not in configured_covers:
                    continue
                timestamp = parse_aware_utc_timestamp(raw_timestamp)
                if timestamp is None or timestamp > now:
                    invalid("last_move_at")

        for field in ("last_known_positions", "last_known_tilt_positions"):
            if field not in stored:
                continue
            values = stored[field]
            if not isinstance(values, dict):
                invalid(field)
            for raw_entity, raw_position in values.items():
                if str(raw_entity) not in configured_covers:
                    continue
                try:
                    position = int(raw_position)
                except (TypeError, ValueError):
                    invalid(field)
                if isinstance(raw_position, bool) or not 0 <= position <= 100:
                    invalid(field)

        for field in ("pending_command_targets", "pending_tilt_targets"):
            if field not in stored:
                continue
            values = stored[field]
            if not isinstance(values, dict):
                invalid(field)
            for raw_entity, raw_intent in values.items():
                if str(raw_entity) not in configured_covers:
                    continue
                if not isinstance(raw_intent, dict):
                    invalid(field)
                try:
                    target = int(raw_intent.get("target"))
                except (TypeError, ValueError):
                    invalid(field)
                expires_at = parse_aware_utc_timestamp(
                    raw_intent.get("expires_at")
                )
                if (
                    isinstance(raw_intent.get("target"), bool)
                    or not 0 <= target <= 100
                    or expires_at is None
                    or expires_at - now > _PENDING_TARGET_HORIZON
                ):
                    invalid(field)

        if "last_command_origins" in stored:
            values = stored["last_command_origins"]
            if not isinstance(values, dict):
                invalid("last_command_origins")
            for raw_entity, raw_origin in values.items():
                if str(raw_entity) not in configured_covers:
                    continue
                if not isinstance(raw_origin, dict):
                    invalid("last_command_origins")
                origin = raw_origin.get("origin")
                issued_at = parse_aware_utc_timestamp(
                    raw_origin.get("issued_at")
                )
                if (
                    not isinstance(origin, str)
                    or not origin.strip()
                    or issued_at is None
                    or issued_at > now
                ):
                    invalid("last_command_origins")

        if "weather_protection" in stored:
            weather = stored["weather_protection"]
            if not isinstance(weather, dict):
                invalid("weather_protection")
            protection_kinds = {"storm", "wind", "rain", "frost"}
            active = weather.get("active")
            if active is not None and (
                not isinstance(active, str) or active not in protection_kinds
            ):
                invalid("weather_protection.active")
            valid_markers: dict[str, set[str]] = {
                "seen_since": set(),
                "clear_since": set(),
            }
            for field, markers in valid_markers.items():
                raw_markers = weather.get(field, {})
                if not isinstance(raw_markers, dict):
                    invalid(f"weather_protection.{field}")
                for raw_kind, raw_timestamp in raw_markers.items():
                    kind = str(raw_kind)
                    if kind not in protection_kinds:
                        continue
                    timestamp = parse_aware_utc_timestamp(raw_timestamp)
                    if timestamp is None or timestamp > now:
                        invalid(f"weather_protection.{field}")
                    markers.add(kind)
            if active is not None and not any(
                active in markers for markers in valid_markers.values()
            ):
                invalid("weather_protection.active")

        raw_retry_at = stored.get("provider_retry_at")
        if "provider_retry_at" in stored and raw_retry_at is not None:
            retry_at = parse_aware_utc_timestamp(raw_retry_at)
            if retry_at is None or retry_at - now > timedelta(minutes=15):
                invalid("provider_retry_at")
        if "provider_retry_attempts" in stored:
            attempts = stored["provider_retry_attempts"]
            if (
                not isinstance(attempts, int)
                or isinstance(attempts, bool)
                or not 0 <= attempts <= _MAX_COMMAND_RETRIES
            ):
                invalid("provider_retry_attempts")

    async def _async_restore_control_state(self) -> None:
        """Restore mode and enable state before any automatic movement."""
        try:
            stored = await async_load_persistent_store(
                self.hass, self._control_store
            )
        except Exception as err:
            # Defaulting to enabled automatic control when the safety store is
            # temporarily unreadable is unsafe. Keep the entry unloaded and let
            # Home Assistant retry without mutating the failed store.
            raise ConfigEntryNotReady(
                "Could not safely restore Smart Shading Control runtime state"
            ) from err
        if stored is None:
            return
        if not isinstance(stored, dict):
            raise ConfigEntryNotReady(
                "Smart Shading Control runtime state has an invalid structure"
            )
        now = dt_util.utcnow()
        covers = self.all_covers
        self._validate_control_state_safety(stored, now=now, covers=covers)
        mode = stored.get("mode")
        if mode in {
            MODE_AUTOMATIC,
            MODE_HEAT_PROTECTION,
            MODE_OPEN,
            MODE_CLOSED,
            MODE_PAUSE,
        }:
            self.mode = str(mode)
            self._mode_state_loaded = True
        enabled = stored.get("enabled")
        if enabled is not None:
            self.enabled = normalize_boolean(enabled, self.enabled)
            self._enabled_state_loaded = True
        raw_check = stored.get("last_time_rule_check")
        if raw_check:
            parsed = dt_util.parse_datetime(str(raw_check))
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=dt_util.UTC)
                self._last_time_rule_check = dt_util.as_local(parsed)
        raw_releases = stored.get("time_rule_manual_releases")
        if isinstance(raw_releases, list):
            self._time_rule_manual_releases = {
                str(item) for item in raw_releases if str(item) in self.all_covers
            }
        raw_scheduled_closes = stored.get("scheduled_close_covers")
        if isinstance(raw_scheduled_closes, list):
            self._scheduled_close_covers = {
                str(item)
                for item in raw_scheduled_closes
                if str(item) in self.all_covers
            }
        raw_occurrences = stored.get("executed_time_rule_occurrences")
        if isinstance(raw_occurrences, list):
            self._executed_time_rule_occurrences = {
                str(item) for item in raw_occurrences[-1000:] if item
            }
        raw_pending_opens = stored.get("pending_time_rule_opens")
        if isinstance(raw_pending_opens, dict):
            restored_pending: dict[str, datetime] = {}
            for entity_id, raw_expiry in raw_pending_opens.items():
                entity_id = str(entity_id)
                if entity_id not in self.all_covers:
                    continue
                parsed = dt_util.parse_datetime(str(raw_expiry))
                if parsed is None:
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=dt_util.UTC)
                expiry = dt_util.as_utc(parsed)
                if expiry > now and expiry - now <= timedelta(days=1):
                    restored_pending[entity_id] = expiry
            self._pending_time_rule_opens = restored_pending
        raw_pending_closes = stored.get("pending_time_rule_closes")
        if isinstance(raw_pending_closes, list):
            self._pending_time_rule_closes = {
                str(item)
                for item in raw_pending_closes
                if str(item) in self.all_covers
            }
        raw_close_ready = stored.get("pending_time_rule_close_ready_at")
        if isinstance(raw_close_ready, dict):
            restored_ready: dict[str, datetime] = {}
            for entity_id, raw_retry_at in raw_close_ready.items():
                entity_id = str(entity_id)
                if entity_id not in self._pending_time_rule_closes:
                    continue
                parsed = dt_util.parse_datetime(str(raw_retry_at))
                if parsed is None:
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=dt_util.UTC)
                retry_at = dt_util.as_utc(parsed)
                if retry_at - now <= timedelta(minutes=15):
                    restored_ready[entity_id] = retry_at
            self._pending_time_rule_close_ready_at = restored_ready

        min_interval = timedelta(
            minutes=max(0, int(self.config.get(CONF_MIN_MOVE_INTERVAL, 0)))
        )
        raw_last_moves = stored.get("last_move_at")
        if min_interval and isinstance(raw_last_moves, dict):
            for raw_entity, raw_timestamp in raw_last_moves.items():
                entity_id = str(raw_entity)
                timestamp = parse_utc_timestamp(raw_timestamp)
                if (
                    entity_id in covers
                    and timestamp is not None
                    and timestamp <= now
                    and now - timestamp < min_interval
                ):
                    self._last_move[entity_id] = timestamp

        for storage_key, target_positions in (
            ("last_known_positions", self._last_known_positions),
            ("last_known_tilt_positions", self._last_known_tilt_positions),
        ):
            raw_known_positions = stored.get(storage_key)
            if not isinstance(raw_known_positions, dict):
                continue
            for raw_entity, raw_position in raw_known_positions.items():
                entity_id = str(raw_entity)
                try:
                    position = int(raw_position)
                except (TypeError, ValueError):
                    continue
                if entity_id in covers and 0 <= position <= 100:
                    target_positions[entity_id] = position

        grace = timedelta(seconds=COMMAND_GRACE_SECONDS)
        self._last_command = restore_recent_target_commands(
            stored.get("last_commands"),
            now=now,
            allowed_keys=covers,
            max_age=grace,
        )
        self._last_tilt_command = restore_recent_target_commands(
            stored.get("last_tilt_commands"),
            now=now,
            allowed_keys=covers,
            max_age=grace,
        )
        self._pending_command_targets = restore_pending_target_commands(
            stored.get("pending_command_targets"),
            now=now,
            allowed_keys=covers,
            max_future=_PENDING_TARGET_HORIZON,
        )
        self._pending_tilt_targets = restore_pending_target_commands(
            stored.get("pending_tilt_targets"),
            now=now,
            allowed_keys=covers,
            max_future=_PENDING_TARGET_HORIZON,
        )
        self._command_contexts = restore_future_timestamps(
            stored.get("command_contexts"),
            now=now,
            max_future=timedelta(seconds=COMMAND_GRACE_SECONDS),
        )
        raw_context_covers = stored.get("command_context_covers")
        if isinstance(raw_context_covers, dict):
            self._command_context_covers = {
                str(context_id): str(entity_id)
                for context_id, entity_id in raw_context_covers.items()
                if str(context_id) in self._command_contexts
                and str(entity_id) in covers
            }
        self._manual_detection_suppressed_until = restore_future_timestamps(
            stored.get("manual_detection_suppressed_until"),
            now=now,
            allowed_keys=covers,
            max_future=timedelta(seconds=COMMAND_GRACE_SECONDS),
        )
        self._last_command_origin = restore_origin_markers(
            stored.get("last_command_origins"),
            now=now,
            allowed_keys=covers,
        )

        raw_levels = stored.get("previous_levels")
        if isinstance(raw_levels, dict):
            self._previous_level = {
                str(orientation): str(level)
                for orientation, level in raw_levels.items()
                if str(orientation) in _ORIENTATION_CONFIG
                and str(level) in {"normal", "preventive", "heat", "strong"}
            }
        self._temperature_samples.extend(
            restore_temperature_samples(
                stored.get("temperature_samples"),
                now=now,
                horizon=timedelta(hours=2),
                limit=48,
            )
        )
        self._weather.restore_storage_state(
            stored.get("weather_protection"), now=now
        )
        self._active_weather_protection = self._weather.active_protection
        try:
            self._command_retry_attempts = max(
                0,
                min(
                    _MAX_COMMAND_RETRIES,
                    int(stored.get("provider_retry_attempts", 0)),
                ),
            )
        except (TypeError, ValueError):
            self._command_retry_attempts = 0
        retry_at = parse_utc_timestamp(stored.get("provider_retry_at"))
        if (
            retry_at is not None
            and retry_at > now
            and retry_at - now <= timedelta(minutes=15)
        ):
            self._command_retry_at = retry_at

        raw_forecast = stored.get("forecast_cache")
        configured_source = str(self.config.get(CONF_WEATHER_ENTITY) or "") or None
        if isinstance(raw_forecast, dict) and raw_forecast.get("source") == configured_source:
            updated_at = parse_utc_timestamp(raw_forecast.get("updated_at"))
            max_age = timedelta(minutes=_FORECAST_STALE_MINUTES)
            if (
                updated_at is not None
                and updated_at <= now
                and now - updated_at <= max_age
            ):
                restored_forecast: list[dict[str, Any]] = []
                raw_items = raw_forecast.get("items")
                if isinstance(raw_items, list):
                    for raw_item in raw_items:
                        if not isinstance(raw_item, dict):
                            continue
                        try:
                            temperature = float(raw_item.get("temperature"))
                        except (TypeError, ValueError):
                            continue
                        if isfinite(temperature):
                            restored_forecast.append({"temperature": temperature})
                self._forecast = restored_forecast
                self._forecast_updated = updated_at
                raw_type = str(raw_forecast.get("type") or "")
                self._forecast_type = (
                    raw_type
                    if raw_type in {"hourly", "daily", "twice_daily"}
                    else None
                )
                self._forecast_source = configured_source

    async def async_save_control_state(self) -> None:
        """Persist the current controller state in write order."""
        async with self._control_state_lock:
            try:
                await self._control_store.async_save(
                    {
                        "enabled": bool(self.enabled),
                        "mode": str(self.mode),
                        "last_time_rule_check": (
                            self._last_time_rule_check.isoformat()
                            if self._last_time_rule_check is not None
                            else None
                        ),
                        "time_rule_manual_releases": sorted(
                            self._time_rule_manual_releases
                        ),
                        "scheduled_close_covers": sorted(
                            self._scheduled_close_covers
                        ),
                        "executed_time_rule_occurrences": list(
                            sorted(
                                self._executed_time_rule_occurrences,
                                key=_time_rule_occurrence_sort_key,
                            )[-1000:]
                        ),
                        "pending_time_rule_opens": {
                            entity: expiry.isoformat()
                            for entity, expiry in self._pending_time_rule_opens.items()
                        },
                        "pending_time_rule_closes": sorted(
                            self._pending_time_rule_closes
                        ),
                        "pending_time_rule_close_ready_at": {
                            entity: retry_at.isoformat()
                            for entity, retry_at in self._pending_time_rule_close_ready_at.items()
                            if entity in self._pending_time_rule_closes
                        },
                        **self._runtime_storage_state(),
                    }
                )
                self._last_control_state_save = dt_util.utcnow()
            except Exception:
                _LOGGER.debug("Could not persist controller state", exc_info=True)

    async def _async_restore_manual_overrides(self) -> None:
        """Restore each non-expired manual override from its absolute expiry."""
        try:
            stored = await async_load_persistent_store(
                self.hass, self._override_store
            )
        except Exception as err:
            # Do not continue with an empty override set and never canonicalize
            # an I/O/JSON failure back to an empty Store. Automatic control may
            # start only after the persistent protection state was read safely.
            raise ConfigEntryNotReady(
                "Could not safely restore Smart Shading Control manual overrides"
            ) from err

        if stored is not None and not isinstance(stored, dict):
            raise ConfigEntryNotReady(
                "Smart Shading Control manual overrides have an invalid structure"
            )

        now = dt_util.utcnow()
        restored: dict[str, datetime] = {}
        if isinstance(stored, dict):
            for entity_id, raw_expiry in stored.items():
                entity_id = str(entity_id)
                if entity_id not in self.all_covers:
                    continue
                expiry = parse_aware_utc_timestamp(raw_expiry)
                if expiry is None or expiry - now > timedelta(days=1):
                    raise ConfigEntryNotReady(
                        "Smart Shading Control manual override deadline is invalid "
                        f"for {entity_id}"
                    )
                if expiry > now:
                    restored[entity_id] = expiry

        self._manual_overrides = restored
        self._manual_override_details = {
            entity: {
                "cover_entity_id": entity,
                "detected_at": None,
                "expires_at": expiry.isoformat(),
                "trigger": "restored_after_restart",
                "old_state": None,
                "new_state": None,
                "old_position": None,
                "new_position": None,
                "old_tilt_position": None,
                "new_tilt_position": None,
                "user_context": False,
                "parent_context": False,
            }
            for entity, expiry in restored.items()
        }
        # A manual release of a persistent night-close rule is only valid while
        # the associated manual override is still active.
        previous_releases = set(self._time_rule_manual_releases)
        self._time_rule_manual_releases.intersection_update(restored)
        self.data["manual_overrides"] = {
            entity: expiry.isoformat() for entity, expiry in restored.items()
        }
        self.data["manual_override_details"] = {
            entity: dict(details)
            for entity, details in self._manual_override_details.items()
        }
        self.data["time_rule_manual_releases"] = sorted(
            self._time_rule_manual_releases
        )
        if previous_releases != self._time_rule_manual_releases:
            await self.async_save_control_state()
        canonical = {
            entity: expiry.isoformat() for entity, expiry in restored.items()
        }
        if stored != canonical:
            # Remove expired and no-longer-configured entries now; they must not
            # linger and become valid again after a clock/config change.
            self._override_revision += 1
            await self._async_save_manual_overrides(self._override_revision)

    @callback
    def _schedule_override_save(self) -> None:
        """Persist the newest per-cover override state."""
        self._schedule_manual_override_expiry()
        self._override_revision += 1
        revision = self._override_revision
        self._create_entry_task(
            self._async_save_manual_overrides(revision), "persist manual overrides"
        )

    async def _async_save_manual_overrides(self, revision: int) -> None:
        """Persist only the newest override snapshot in write order."""
        async with self._override_save_lock:
            if revision != self._override_revision:
                return
            snapshot = {
                entity: expiry.isoformat()
                for entity, expiry in self._manual_overrides.items()
            }
            try:
                await self._override_store.async_save(snapshot)
            except Exception:
                _LOGGER.debug("Could not persist manual overrides", exc_info=True)

    @callback
    def _schedule_manual_override_expiry(self) -> None:
        """Wake exactly at the earliest absolute manual-override deadline."""
        if self._override_expiry_cancel is not None:
            self._override_expiry_cancel()
            self._override_expiry_cancel = None
        if not self._started or not self._manual_overrides:
            return
        now = dt_util.utcnow()
        expiry = min(self._manual_overrides.values())
        delay = max(0.0, (expiry - now).total_seconds())
        self._override_expiry_cancel = async_call_later(
            self.hass,
            delay,
            self._handle_manual_override_expiry,
        )

    async def _handle_manual_override_expiry(self, _now: datetime) -> None:
        """Expire due per-cover holds, persist them and resume evaluation."""
        self._override_expiry_cancel = None
        if not self._started:
            return
        previous = dict(self._manual_overrides)
        self._purge_expired(
            dt_util.utcnow(),
            schedule_persistence=False,
        )
        if previous != self._manual_overrides:
            self._override_revision += 1
            await self._async_save_manual_overrides(self._override_revision)
            await self.async_save_control_state()
        self._schedule_manual_override_expiry()
        if previous != self._manual_overrides:
            await self.async_evaluate()

    async def _async_enforce_contact_safety(self, contact_entity: str) -> None:
        """Apply contact protection only to automatic night closing.

        Daytime solar and heat shading, explicit room modes and manual cover
        commands remain available with an open or tilted contact. A contact
        only blocks the persistent close state created by a time rule.
        """
        if not self._started:
            return
        mapping = self.config.get(CONF_COVER_CONTACTS) or {}
        if not isinstance(mapping, dict):
            return
        covers = [
            str(cover)
            for cover, contact in mapping.items()
            if str(contact) == contact_entity and str(cover) in self.all_covers
        ]
        if not covers:
            return

        contact_state = self.hass.states.get(contact_entity)
        contact_kind = classify_contact_state(
            contact_state.state if contact_state is not None else None,
            contact_state.attributes if contact_state is not None else None,
        )
        if contact_kind == CONTACT_UNKNOWN:
            create_issue(
                self.hass,
                self.entry.entry_id,
                "contact_unknown",
                entity_id=contact_entity,
                placeholders={"entity": contact_entity, "room": self.room_name},
                severity=ir.IssueSeverity.WARNING,
            )
        else:
            delete_issue(
                self.hass, self.entry.entry_id, "contact_unknown", contact_entity
            )

        now = dt_util.utcnow()
        state_changed = False
        if contact_kind == CONTACT_CLOSED:
            for cover in covers:
                if (
                    cover in self._pending_time_rule_closes
                    and cover in self._scheduled_close_covers
                    and cover not in self._pending_time_rule_close_ready_at
                ):
                    self._pending_time_rule_close_ready_at[cover] = now + timedelta(
                        seconds=_TIME_RULE_CLOSE_CONTACT_DELAY_SECONDS
                    )
                    state_changed = True
            self._schedule_time_rule_close_retry()
            if state_changed:
                await self.async_save_control_state()
            return

        open_target = int(self.config[CONF_OPEN_POSITION])
        for cover in covers:
            if cover not in self._scheduled_close_covers:
                continue
            if cover not in self._pending_time_rule_closes:
                self._pending_time_rule_closes.add(cover)
                state_changed = True
            if self._pending_time_rule_close_ready_at.pop(cover, None) is not None:
                state_changed = True

            # Reverse only a movement or position that was created by the
            # automatic night rule. Manual commands and daytime shading must
            # never be redirected by a contact event.
            origin = self._last_command_origin.get(cover)
            if origin is None or origin[0] != "time_rule_close":
                continue
            cover_state = self.hass.states.get(cover)
            if cover_state is None or cover_state.state in {
                STATE_UNKNOWN,
                STATE_UNAVAILABLE,
            }:
                continue
            current = self._position_from_state(cover_state)
            if current is not None and abs(current - open_target) <= POSITION_TOLERANCE:
                continue
            self._manual_detection_suppressed_until[cover] = (
                now + timedelta(seconds=COMMAND_GRACE_SECONDS)
            )
            if self._cover_requires_emergency_stop(cover, cover_state):
                await self._async_stop_cover(cover, cover_state)
            await self._async_move_cover(
                cover,
                cover_state,
                open_target,
                evaluation_revision=None,
                manual=True,
                priority=PRIORITY_EMERGENCY,
                origin="time_rule_contact_release",
            )

        self._schedule_time_rule_close_retry()
        if state_changed:
            await self.async_save_control_state()
        await self.async_evaluate(force=True)

    def _cover_requires_emergency_stop(
        self, entity_id: str, state: State
    ) -> bool:
        """Return whether a contact fail-safe must stop a closing movement."""
        if state.state == "closing":
            return True
        current = self._position_from_state(state)
        last = self._last_command.get(entity_id)
        return bool(
            last is not None
            and current is not None
            and last[0] < current
            and (dt_util.utcnow() - last[1]).total_seconds() <= COMMAND_GRACE_SECONDS
        )

    async def _async_stop_cover(
        self,
        entity_id: str,
        state: State,
        *,
        manual: bool = False,
        manual_revision: int | None = None,
    ) -> bool:
        """Stop one moving cover through the serialized command queue."""

        def command_is_valid() -> bool:
            return bool(
                self._started
                and (
                    manual_revision is None
                    or manual_revision == self._manual_command_revision
                )
            )

        if not command_is_valid():
            return False
        supported = int(state.attributes.get("supported_features", 0))
        if not supported & int(CoverEntityFeature.STOP):
            create_issue(
                self.hass,
                self.entry.entry_id,
                "cover_stop_unsupported",
                entity_id=entity_id,
                placeholders={"entity": entity_id, "room": self.room_name},
                severity=ir.IssueSeverity.WARNING,
            )
            return False
        delete_issue(self.hass, self.entry.entry_id, "cover_stop_unsupported", entity_id)
        if normalize_boolean(self.config.get(CONF_DRY_RUN), False):
            return True
        now = dt_util.utcnow()
        last_attempt = self._last_stop_attempt.get(entity_id)
        if last_attempt is not None and (now - last_attempt).total_seconds() < 5:
            return True
        self._last_stop_attempt[entity_id] = now
        context = Context()

        def command_started(started_context: Context, issued_at: datetime) -> None:
            self._command_contexts[started_context.id] = issued_at + timedelta(
                seconds=COMMAND_GRACE_SECONDS
            )
            self._command_context_covers[started_context.id] = entity_id
            self._create_entry_task(
                self.async_save_control_state(), "persist stop context"
            )

        self._provider_command_attempted = True
        result = await self._command_queue.async_submit(
            entity_id=entity_id,
            command_type="stop",
            service="stop_cover",
            priority=PRIORITY_MANUAL_STOP if manual else PRIORITY_EMERGENCY,
            coalesce_key="vertical",
            context=context,
            is_valid=command_is_valid,
            on_started=command_started,
        )
        if not result.success:
            self._last_stop_attempt.pop(entity_id, None)
        return self._handle_command_result(
            entity_id,
            result,
            log_message=(
                "Could not stop cover %s after a manual stop request"
                if manual
                else "Could not stop cover %s after contact safety activation"
            ),
        )

    def _handle_command_result(
        self,
        entity_id: str,
        result: CommandResult,
        *,
        log_message: str,
    ) -> bool:
        """Update provider health from one command-queue result."""
        if result.success:
            self._provider_command_succeeded = True
            self._record_provider_success(entity_id)
            return True
        if result.skipped_reason is not None or result.superseded:
            return False

        err = result.error or HomeAssistantError("Unknown cover provider error")
        if isinstance(
            err,
            (ClientError, ConnectionError, TimeoutError, OSError, HomeAssistantError),
        ):
            _LOGGER.warning(log_message + ": %s", entity_id, err)
        else:
            _LOGGER.error(
                log_message,
                entity_id,
                exc_info=(type(err), err, err.__traceback__),
            )
        self._transient_command_failure = True
        self._provider_failures += 1
        self._record_provider_failure(entity_id, err)
        if self._provider_failures >= 3:
            create_issue(
                self.hass,
                self.entry.entry_id,
                "provider_degraded",
                placeholders={"room": self.room_name},
                severity=ir.IssueSeverity.WARNING,
                persistent=True,
            )
        self._schedule_command_retry()
        return False

    def position_from_state(self, state: State | None) -> int | None:
        """Return a normalized vertical cover position for platform consumers."""
        return self._position_from_state(state)

    def _is_opening_request(self, state: State | None, requested: int) -> bool:
        """Return the semantic movement direction for one physical cover."""
        supported = int(state.attributes.get("supported_features", 0)) if state else 0
        return is_opening_target(
            requested,
            self._position_from_state(state),
            int(self.config[CONF_OPEN_POSITION]),
            binary_cover=bool(
                state is not None
                and not bool(supported & int(CoverEntityFeature.SET_POSITION))
            ),
        )

    def _active_weather_safe_position(self) -> int | None:
        """Return the configured target of the currently active movement safety."""
        if not self.enabled or self.mode == MODE_PAUSE:
            return None
        protection = self._weather.active_protection
        if protection == "storm":
            return int(self.config[CONF_STORM_SAFE_POSITION])
        if protection == "wind":
            return int(self.config[CONF_WIND_SAFE_POSITION])
        if protection == "rain":
            return int(self.config[CONF_RAIN_SAFE_POSITION])
        if protection == "frost" and str(
            self.config.get(CONF_FROST_ACTION)
        ) == FROST_ACTION_SAFE_POSITION:
            return int(self.config[CONF_FROST_SAFE_POSITION])
        return None

    def _record_provider_success(self, entity_id: str) -> None:
        """Record a successful provider command for one physical cover."""
        now = dt_util.utcnow()
        health = self._provider_health_by_cover.setdefault(entity_id, {})
        health.update(
            state="ok",
            consecutive_failures=0,
            last_success=now.isoformat(),
            last_error=None,
            last_error_at=None,
            next_retry_attempt=self._command_retry_attempts,
        )
        self.data["last_successful_command"] = now.isoformat()

    def _record_provider_failure(self, entity_id: str, err: Exception) -> None:
        """Record a provider failure for one physical cover."""
        now = dt_util.utcnow()
        health = self._provider_health_by_cover.setdefault(entity_id, {})
        failures = int(health.get("consecutive_failures", 0)) + 1
        error_text = f"{type(err).__name__}: {err}"
        health.update(
            state="degraded",
            consecutive_failures=failures,
            last_error=error_text,
            last_error_at=now.isoformat(),
            next_retry_attempt=min(self._command_retry_attempts + 1, _MAX_COMMAND_RETRIES),
        )
        self.data["last_provider_error"] = error_text
        self.data["last_provider_error_at"] = now.isoformat()

    def _reset_provider_recovery_state(self) -> None:
        """Clear room-wide retry state after a fully successful command cycle."""
        retry_was_active = bool(
            self._command_retry_cancel is not None
            or self._command_retry_at is not None
            or self._command_retry_attempts
        )
        if self._command_retry_cancel is not None:
            self._command_retry_cancel()
            self._command_retry_cancel = None
        self._command_retry_at = None
        self._command_retry_attempts = 0
        self._provider_failures = 0
        self.data["next_provider_retry"] = None
        self.data["last_provider_error"] = None
        self.data["last_provider_error_at"] = None
        delete_issue(self.hass, self.entry.entry_id, "provider_degraded")
        if retry_was_active:
            self._create_entry_task(
                self.async_save_control_state(), "clear provider retry"
            )

    def _append_decision(
        self,
        now: datetime,
        status: str,
        reason_code: str,
        desired: dict[str, int],
        commanded: dict[str, int],
        actual: dict[str, int | None],
    ) -> None:
        """Append one complete machine-readable evaluation record."""
        self._decision_history.append(
            timestamp=now,
            status=status,
            reason_code=reason_code,
            desired_positions=desired,
            commanded_positions=commanded,
            actual_positions=actual,
            dry_run=normalize_boolean(self.config.get(CONF_DRY_RUN), False),
            active_weather_protection=self._active_weather_protection,
            command_queue=self._command_queue.snapshot(),
        )


    async def _async_manual_set_positions(
        self,
        covers: list[str] | tuple[str, ...],
        position: int,
        *,
        command_scope: str,
    ) -> None:
        """Manually position selected room covers through the command queue."""
        configured = set(self.all_covers)
        selected_covers = [
            entity_id
            for entity_id in dict.fromkeys(str(item) for item in covers)
            if entity_id in configured
        ]
        if not selected_covers:
            return

        target = max(0, min(100, int(position)))
        now = dt_util.utcnow()
        config = self.config
        dry_run = normalize_boolean(config.get(CONF_DRY_RUN), False)

        # An explicit command supersedes only pending schedule work for the
        # selected covers. Individual control must not release or cancel a
        # night rule that belongs to another shutter in the same room.
        pending_changed = self._clear_pending_time_rules_for_covers(
            selected_covers
        )

        # Invalidate automatic plans once, but keep a separate generation for
        # this user transaction. Ordinary sensor/minute updates must not abort a
        # serial multi-cover command after its first item.
        self._input_revision += 1
        self._manual_command_revision += 1
        command_revision = self._manual_command_revision
        results: dict[str, dict[str, Any]] = {}
        successful: list[str] = []
        dry_run_covers: list[str] = []
        noop_covers: list[str] = []

        expiry = self._manual_override_expiry(
            now, max(0, int(config[CONF_MANUAL_OVERRIDE_MINUTES]))
        )
        trigger = (
            "integration_manual_group"
            if command_scope == "group"
            else "integration_manual_individual"
        )
        prior_manual_state: dict[
            str, tuple[datetime | None, dict[str, Any] | None, bool]
        ] = {}

        # Install a provisional per-cover hold before the first provider await.
        # This makes the whole user request atomically visible to concurrent
        # evaluations. Failed/unavailable covers are rolled back below, while a
        # process restart safely retains the user's already accepted intent.
        if expiry is not None and not dry_run:
            for entity_id in selected_covers:
                previous_details = self._manual_override_details.get(entity_id)
                prior_manual_state[entity_id] = (
                    self._manual_overrides.get(entity_id),
                    dict(previous_details) if previous_details is not None else None,
                    entity_id in self._time_rule_manual_releases,
                )
                state = self.hass.states.get(entity_id)
                self._manual_overrides[entity_id] = expiry
                self._manual_override_details[entity_id] = {
                    "cover_entity_id": entity_id,
                    "detected_at": now.isoformat(),
                    "expires_at": expiry.isoformat(),
                    "trigger": trigger,
                    "old_state": state.state if state is not None else None,
                    "new_state": None,
                    "old_position": self._position_from_state(state),
                    "new_position": target,
                    "user_context": True,
                    "parent_context": False,
                    "transaction_revision": command_revision,
                    "transaction_state": "pending",
                }
                self._time_rule_manual_releases.add(entity_id)
            self._sync_manual_override_data()
            self._override_revision += 1
            await self._async_save_manual_overrides(self._override_revision)
            self._schedule_manual_override_expiry()
            await self.async_save_control_state()

        for entity_id in selected_covers:
            if (
                not self._started
                or command_revision != self._manual_command_revision
            ):
                break
            state = self.hass.states.get(entity_id)
            if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
                results[entity_id] = {
                    "requested_position": target,
                    "effective_position": target,
                    "safety_forced": False,
                    "result": "unavailable",
                }
                continue

            opening_requested = self._is_opening_request(state, target)
            safety_position = self._active_weather_safe_position()
            safety_applies = safety_position is not None and not opening_requested
            protected_target = (
                max(target, safety_position)
                if safety_applies and safety_position is not None
                else target
            )
            supported = int(state.attributes.get("supported_features", 0))
            effective_target = protected_target
            if not supported & int(CoverEntityFeature.SET_POSITION):
                effective_target = binary_cover_target(
                    protected_target,
                    safety_forced=safety_applies,
                    opening_requested=opening_requested,
                )

            current = self._position_from_state(state)
            if (
                current is not None
                and abs(current - effective_target) <= POSITION_TOLERANCE
            ):
                results[entity_id] = {
                    "requested_position": target,
                    "effective_position": effective_target,
                    "safety_forced": safety_applies,
                    "result": "already_at_target",
                }
                noop_covers.append(entity_id)
                continue

            accepted = await self._async_move_cover(
                entity_id,
                state,
                effective_target,
                manual=True,
                manual_revision=command_revision,
                priority=(
                    PRIORITY_SAFETY
                    if safety_position is not None
                    else PRIORITY_MANUAL
                ),
                origin=(
                    "manual_group"
                    if command_scope == "group"
                    else "manual_individual"
                ),
            )
            results[entity_id] = {
                "requested_position": target,
                "effective_position": effective_target,
                "safety_forced": safety_applies,
                "result": (
                    "dry_run" if dry_run else "accepted" if accepted else "failed"
                ),
            }
            if accepted and dry_run:
                dry_run_covers.append(entity_id)
            elif accepted:
                successful.append(entity_id)

        retained_covers = set(successful) | set(noop_covers)
        manual_state_changed = False
        for cover, (previous_expiry, previous_details, previous_release) in (
            prior_manual_state.items()
        ):
            current_details = self._manual_override_details.get(cover)
            if (
                not isinstance(current_details, dict)
                or current_details.get("transaction_revision") != command_revision
            ):
                # A newer manual transaction owns this cover already.
                continue
            manual_state_changed = True
            if cover in retained_covers:
                current_details = dict(current_details)
                current_details.pop("transaction_revision", None)
                current_details["transaction_state"] = "accepted"
                self._manual_override_details[cover] = current_details
                continue

            if previous_expiry is not None and previous_expiry > dt_util.utcnow():
                self._manual_overrides[cover] = previous_expiry
                if previous_details is not None:
                    self._manual_override_details[cover] = previous_details
                else:
                    self._manual_override_details.pop(cover, None)
            else:
                self._manual_overrides.pop(cover, None)
                self._manual_override_details.pop(cover, None)
            if previous_release:
                self._time_rule_manual_releases.add(cover)
            else:
                self._time_rule_manual_releases.discard(cover)

        if successful or manual_state_changed or pending_changed:
            if manual_state_changed:
                self._sync_manual_override_data()
                self._schedule_override_save()
            await self.async_save_control_state()

        provider_results = {
            str(item.get("result"))
            for item in results.values()
            if isinstance(item, dict)
        }
        if successful and not provider_results.intersection({"failed", "unavailable"}):
            self._reset_provider_recovery_state()

        command_record = {
            "timestamp": now.isoformat(),
            "scope": command_scope,
            "requested_position": target,
            "requested_covers": list(selected_covers),
            "successful_covers": sorted(successful),
            "dry_run_covers": sorted(dry_run_covers),
            "already_at_target_covers": sorted(noop_covers),
            "failed_or_skipped_covers": sorted(
                set(selected_covers)
                - set(successful)
                - set(dry_run_covers)
                - set(noop_covers)
            ),
            "results": results,
        }
        if command_scope == "group":
            self.data["last_manual_group_command"] = command_record
        else:
            self.data["last_manual_cover_command"] = command_record

        self._sync_manual_override_data()
        self.data["provider_health_by_cover"] = {
            entity: dict(health)
            for entity, health in self._provider_health_by_cover.items()
        }
        self._sync_pending_time_rule_data()
        self._publish()

        failed_covers = sorted(
            entity_id
            for entity_id, result in results.items()
            if result.get("result") in {"failed", "unavailable"}
        )
        if failed_covers:
            succeeded = sorted(set(successful) | set(noop_covers))
            detail = ", ".join(failed_covers)
            if succeeded:
                raise HomeAssistantError(
                    "Manual cover command was only partially applied; failed: "
                    f"{detail}"
                )
            raise HomeAssistantError(
                f"Manual cover command could not be applied: {detail}"
            )

    async def async_group_set_position(self, position: int) -> None:
        """Manually move every configured cover in this room."""
        await self._async_manual_set_positions(
            self.all_covers, position, command_scope="group"
        )

    async def async_cover_set_position(
        self, entity_id: str, position: int
    ) -> None:
        """Manually move one configured physical cover."""
        await self._async_manual_set_positions(
            [entity_id], position, command_scope="individual"
        )

    async def _async_manual_stop_covers(
        self, covers: list[str] | tuple[str, ...]
    ) -> None:
        """Stop and immediately protect each selected cover from automation."""
        if not self._started:
            return
        configured = set(self.all_covers)
        selected_covers = [
            entity_id
            for entity_id in dict.fromkeys(str(item) for item in covers)
            if entity_id in configured
        ]
        if not selected_covers:
            return

        pending_changed = self._clear_pending_time_rules_for_covers(
            selected_covers
        )
        self._input_revision += 1
        self._manual_command_revision += 1
        command_revision = self._manual_command_revision
        now = dt_util.utcnow()
        dry_run = normalize_boolean(self.config.get(CONF_DRY_RUN), False)
        expiry = self._manual_override_expiry(
            now, max(0, int(self.config[CONF_MANUAL_OVERRIDE_MINUTES]))
        )

        states = {
            entity_id: self.hass.states.get(entity_id)
            for entity_id in selected_covers
        }
        needs_stop: set[str] = set()
        for entity_id, state in states.items():
            if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
                continue
            last = self._last_command.get(entity_id)
            current = self._position_from_state(state)
            pending_command = bool(
                last is not None
                and (now - last[1]).total_seconds() <= COMMAND_GRACE_SECONDS
                and (
                    current is None
                    or abs(current - last[0]) > POSITION_TOLERANCE
                )
            )
            if state.state in {"opening", "closing"} or pending_command:
                needs_stop.add(entity_id)

        # STOP is itself an explicit manual takeover. Establish the hold and
        # remove stale automatic intent before awaiting any provider. This is
        # deliberately independent of whether a provider emits a stop event.
        if not dry_run:
            for entity_id in selected_covers:
                if expiry is not None:
                    state = states[entity_id]
                    self._manual_overrides[entity_id] = expiry
                    self._manual_override_details[entity_id] = {
                        "cover_entity_id": entity_id,
                        "detected_at": now.isoformat(),
                        "expires_at": expiry.isoformat(),
                        "trigger": "integration_manual_stop",
                        "old_state": state.state if state is not None else None,
                        "new_state": "stopped",
                        "old_position": self._position_from_state(state),
                        "new_position": self._position_from_state(state),
                        "user_context": True,
                        "parent_context": False,
                    }
                    self._time_rule_manual_releases.add(entity_id)
                self._clear_command_markers_for_cover(
                    entity_id, include_tilt=True
                )
            self._sync_manual_override_data()
            if expiry is not None:
                self._override_revision += 1
                await self._async_save_manual_overrides(self._override_revision)
                self._schedule_manual_override_expiry()
            await self.async_save_control_state()

        results: dict[str, str] = {}
        for entity_id in selected_covers:
            if command_revision != self._manual_command_revision:
                break
            state = states[entity_id]
            if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
                results[entity_id] = "unavailable"
                continue
            if entity_id not in needs_stop:
                results[entity_id] = "held"
                continue
            accepted = await self._async_stop_cover(
                entity_id,
                state,
                manual=True,
                manual_revision=command_revision,
            )
            results[entity_id] = (
                "dry_run" if dry_run else "accepted" if accepted else "failed"
            )

        if pending_changed or not dry_run:
            await self.async_save_control_state()
        self._sync_pending_time_rule_data()
        self._publish()

        failed_covers = sorted(
            entity_id
            for entity_id, result in results.items()
            if result in {"failed", "unavailable"}
        )
        if failed_covers:
            raise HomeAssistantError(
                "Manual stop could not be fully applied; failed: "
                + ", ".join(failed_covers)
            )

    async def async_group_stop(self) -> None:
        """Stop all moving room covers that support stop."""
        await self._async_manual_stop_covers(self.all_covers)

    async def async_cover_stop(self, entity_id: str) -> None:
        """Stop one moving physical cover."""
        await self._async_manual_stop_covers([entity_id])

    async def async_set_enabled(self, enabled: bool) -> None:
        """Enable or disable automatic movements."""
        self.enabled = enabled
        self._input_revision += 1
        if not enabled:
            self._pending_time_rule_opens.clear()
            self._clear_pending_time_rule_closes()
            self.data["pending_time_rule_opens"] = {}
            self.data["pending_time_rule_closes"] = {}
            self.data["pending_time_rule_close_count"] = 0
        await self.async_save_control_state()
        if enabled:
            await self.async_evaluate(force=True)
        else:
            self._set_reason(STATUS_DISABLED, "control_disabled")
            self._publish()

    async def async_set_mode(self, mode: str) -> None:
        """Set one exclusive operating mode and execute it immediately."""
        self.mode = mode
        self._input_revision += 1
        # Selecting a mode is an explicit command. It activates room control,
        # ends the previous automatic/manual mode and bypasses move throttling.
        self.enabled = True
        self._manual_overrides.clear()
        self._manual_override_details.clear()
        self.data["manual_overrides"] = {}
        self.data["manual_override_details"] = {}
        self._time_rule_manual_releases.clear()
        self._pending_time_rule_opens.clear()
        self._clear_pending_time_rule_closes()
        self._schedule_override_save()
        await self.async_save_control_state()
        await self.async_evaluate(force=True)

    async def async_clear_manual_overrides(self) -> None:
        """Clear temporary overrides and manual time-rule releases."""
        self._manual_overrides.clear()
        self._manual_override_details.clear()
        self.data["manual_overrides"] = {}
        self.data["manual_override_details"] = {}
        self._time_rule_manual_releases.clear()
        self._clear_pending_time_rule_closes()
        self._input_revision += 1
        self._schedule_override_save()
        await self.async_save_control_state()
        await self.async_evaluate(force=True)

    def decision_history_export(self) -> dict[str, Any]:
        """Return the privacy-cleaned chronicle used by HA diagnostics."""
        return self._decision_history.sanitized(self.all_covers)

    async def async_clear_decision_log(self) -> None:
        """Clear the in-memory machine-readable decision history."""
        self._decision_history.clear()
        self._publish()

    async def async_evaluate(self, force: bool = False) -> None:
        """Evaluate one room and retain every mid-cycle rerun request."""
        if not self._started:
            return
        if self._evaluation_lock.locked():
            self._evaluation_pending = True
            self._evaluation_force = self._evaluation_force or force
            return

        async with self._evaluation_lock:
            requested_force = force
            while self._started:
                effective_force = requested_force or self._evaluation_force
                self._evaluation_pending = False
                self._evaluation_force = False
                await self._async_evaluate_locked(effective_force)
                if not self._evaluation_pending:
                    break
                requested_force = self._evaluation_force

    def _resolve_solar_event(self, event: str, event_date: date) -> datetime | None:
        """Resolve solar events from the selected common sun source."""
        config = self.config
        if str(config.get(CONF_SUN_EVENT_SOURCE)) == SUN_EVENT_SOURCE_ENTITY:
            entity_id = str(config.get(CONF_SUN_ENTITY) or "sun.sun")
            state = self.hass.states.get(entity_id)
            attribute = "next_rising" if event == "sunrise" else "next_setting"
            raw_value = state.attributes.get(attribute) if state is not None else None
            parsed = dt_util.parse_datetime(str(raw_value)) if raw_value else None
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=dt_util.UTC)
                local_event = dt_util.as_local(parsed)
                # A sun entity exposes only its *next* event. Reusing that
                # clock time for another nominal date would introduce a growing
                # seasonal error. Use it only for the date it actually describes
                # and let Home Assistant's astral helper resolve other dates.
                if local_event.date() == event_date:
                    return local_event
        return get_astral_event_date(self.hass, event, event_date)

    @staticmethod
    def _select_time_rule_open_reconciliation(
        time_rule_states: dict[str, str],
        *,
        full_reconciliation: bool,
        availability_covers: set[str],
    ) -> set[str]:
        """Select current OPEN states for full or cover-specific recovery."""
        return {
            cover
            for cover, action in time_rule_states.items()
            if action == RULE_ACTION_OPEN
            and (full_reconciliation or cover in availability_covers)
        }

    async def _async_evaluate_locked(self, force: bool) -> None:
        """Evaluate one coherent snapshot while the controller lock is held."""
        now = dt_util.utcnow()
        evaluation_revision = self._input_revision
        self._transient_command_failure = False
        self._provider_command_attempted = False
        self._provider_command_succeeded = False
        self._purge_expired(now)
        runtime_state_before = self._runtime_storage_state()
        config = self.config
        all_covers = self.all_covers

        if not all_covers:
            self.data.update(
                status=STATUS_UNAVAILABLE,
                reason="no_covers",
                reason_code="no_covers",
                reason_context={},
                last_evaluation=now.isoformat(),
            )
            self._publish()
            return

        self._update_repairs(all_covers)
        self.data["commanded_tilt_positions"] = {}
        self.data["would_command_tilt_positions"] = {}
        await self._async_refresh_forecast_if_needed(now)

        room_temperature = self._temperature_state(
            config.get(CONF_ROOM_TEMP_SENSOR)
        )
        outside_temperature = self._weather.outside_temperature()
        self._record_temperature(now, room_temperature)
        trend = self._temperature_trend()
        forecast_hours = int(config[CONF_FORECAST_HOURS])
        forecast_items = forecast_hours
        if self._forecast_type == "daily":
            # Include the current period and one boundary period so a short
            # horizon around midnight does not miss the following day's high.
            forecast_items = max(1, (forecast_hours + 23) // 24 + 1)
        elif self._forecast_type == "twice_daily":
            forecast_items = max(1, (forecast_hours + 11) // 12 + 1)
        forecast_max = forecast_max_temperature(
            self._forecast,
            forecast_items,
        )

        sun_state = self.hass.states.get(str(config.get(CONF_SUN_ENTITY) or "sun.sun"))
        sun_azimuth = self._attribute_float(sun_state, "azimuth")
        sun_elevation = self._attribute_float(sun_state, "elevation")
        sun_above_horizon = bool(
            sun_state is not None and sun_state.state == "above_horizon"
        )
        dynamic_daylight = (
            sun_above_horizon
            and sun_elevation is not None
            and sun_elevation >= float(config[CONF_MIN_SUN_ELEVATION])
        )
        condition, radiation = self._weather.radiation_factor()
        wind_speed = self._weather.wind_speed()
        rain_active = self._weather.rain_active(condition)

        calculated_facade_azimuths = facade_azimuths(
            float(config[CONF_AZIMUTH_NORTH])
        )
        incidence: dict[str, float] = {}
        direct: dict[str, bool] = {}
        for orientation, covers in self.covers_by_orientation.items():
            value = 0.0
            if (
                covers
                and dynamic_daylight
                and sun_azimuth is not None
                and sun_elevation is not None
            ):
                value = sun_incidence(
                    sun_azimuth,
                    sun_elevation,
                    calculated_facade_azimuths[orientation],
                    float(config[CONF_SUN_HALF_ANGLE]),
                    float(config[CONF_MIN_SUN_ELEVATION]),
                    radiation,
                )
            incidence[orientation] = round(value, 3)
            direct[orientation] = value >= 0.12

        sun_load = max(incidence.values(), default=0.0)
        risk = calculate_heat_risk(
            room_temperature=room_temperature,
            outside_temperature=outside_temperature,
            forecast_max=forecast_max,
            sun_load=sun_load,
            temperature_trend=trend,
            comfort_temperature=float(config[CONF_COMFORT_TEMPERATURE]),
            heat_temperature=float(config[CONF_HEAT_TEMPERATURE]),
            forecast_threshold=float(config[CONF_FORECAST_THRESHOLD]),
        )

        raw_assignments = config.get(CONF_COVER_CONTACTS) or {}
        assignments: dict[str, str] = {}
        if isinstance(raw_assignments, dict):
            assignments = {
                str(cover): str(contact)
                for cover, contact in raw_assignments.items()
                if str(cover) in all_covers and contact
            }
        classified_contacts: dict[str, str] = {}
        for entity_id in set(assignments.values()):
            contact_state = self.hass.states.get(entity_id)
            classified_contacts[entity_id] = classify_contact_state(
                contact_state.state if contact_state is not None else None,
                contact_state.attributes if contact_state is not None else None,
            )
        contacts = summarize_cover_contacts(
            all_covers,
            assignments,
            classified_contacts,
        )

        local_now = dt_util.as_local(now)
        workday_entity = config.get(CONF_WORKDAY_ENTITY)
        is_workday = self._workday_state(workday_entity)

        # Time rules are always executed from the room entry. Central rules are
        # copied into every room when saved globally, so one room's local rules
        # can never suppress the central sunset/sunrise event of another room.
        combined_rules: list[dict[str, Any]] = []
        for raw_rule in as_list(config.get(CONF_TIME_RULES)):
            if isinstance(raw_rule, dict) and normalize_boolean(
                raw_rule.get(CONF_RULE_ENABLED), True
            ):
                rule = dict(raw_rule)
                rule[CONF_RULE_SCOPE] = RULE_SCOPE_ROOM
                combined_rules.append(rule)

        time_rule_conflicts = detect_rule_conflicts(combined_rules, all_covers)
        self.data["time_rule_conflicts"] = time_rule_conflicts
        self.data["time_rule_conflict_count"] = len(time_rule_conflicts)

        await self._async_prepare_workday_dates(
            local_now,
            combined_rules,
            str(workday_entity) if workday_entity else None,
            is_workday,
        )
        workday_dependent = any(
            str(rule.get(CONF_RULE_DAY_TYPE) or DAY_TYPE_ANY) != DAY_TYPE_ANY
            for rule in combined_rules
        )
        workday_data_ready = self._workday_history_ready(
            local_now,
            combined_rules,
            str(workday_entity) if workday_entity else None,
        )
        workday_data_recovered = (
            self._workday_data_ready is False and workday_data_ready
        )
        self._workday_data_ready = workday_data_ready

        # Rules are one-shot opening or closing events. A short catch-up window
        # tolerates delayed callbacks and brief Home Assistant restarts. Day-type
        # rules keep a longer horizon so a temporary Workday outage cannot
        # silently consume the event it was unable to classify.
        catch_up_limit = (
            timedelta(days=1) if workday_dependent else timedelta(minutes=10)
        )
        rule_window_start = self._last_time_rule_check
        if (
            rule_window_start is None
            or rule_window_start.tzinfo is None
            or rule_window_start >= local_now
            or local_now - rule_window_start > catch_up_limit
        ):
            rule_window_start = local_now - timedelta(minutes=2)

        common_rule_kwargs = {
            "solar_resolver": self._resolve_solar_event,
            "is_workday": is_workday,
            "day_type_resolver": (
                self._workday_for_date if workday_entity else None
            ),
            "nonexistent_policy": str(config[CONF_DST_NONEXISTENT_POLICY]),
            "ambiguous_policy": str(config[CONF_DST_AMBIGUOUS_POLICY]),
        }
        time_rule_states, time_rule_state_details = resolve_rule_states(
            combined_rules,
            local_now,
            all_covers,
            **common_rule_kwargs,
        )
        time_rule_actions, triggered_time_rules, new_occurrences = resolve_rule_actions(
            combined_rules,
            rule_window_start,
            local_now,
            all_covers,
            already_executed=self._executed_time_rule_occurrences,
            **common_rule_kwargs,
        )
        control_state_changed = False
        # Never move the one-shot cursor past an event whose day type could not
        # be resolved. Already-executed occurrence keys suppress duplicates while
        # the cursor is intentionally held back.
        if workday_data_ready:
            self._last_time_rule_check = local_now
            if combined_rules and (
                self._last_control_state_save is None
                or now - self._last_control_state_save >= timedelta(minutes=5)
            ):
                # Periodically checkpoint the event cursor even during otherwise
                # quiet rooms. This bounds restart catch-up without writing the
                # Store on every minute tick.
                control_state_changed = True
        if new_occurrences:
            self._executed_time_rule_occurrences.update(new_occurrences)
            if len(self._executed_time_rule_occurrences) > 1000:
                self._executed_time_rule_occurrences = set(
                    sorted(
                        self._executed_time_rule_occurrences,
                        key=_time_rule_occurrence_sort_key,
                    )[-1000:]
                )
            control_state_changed = True

        # A close event starts a persistent scheduled closure. The next open
        # event releases that closure. Opening events remain pending briefly so
        # a transient provider outage cannot silently consume the one-shot event.
        for cover, action in time_rule_actions.items():
            if action not in {RULE_ACTION_OPEN, RULE_ACTION_CLOSE}:
                continue
            if cover in self._time_rule_manual_releases:
                self._time_rule_manual_releases.discard(cover)
                control_state_changed = True
            previous_pending = self._pending_time_rule_opens.pop(cover, None)
            if previous_pending is not None:
                control_state_changed = True
            if (
                action == RULE_ACTION_OPEN
                and self.enabled
                and self.mode == MODE_AUTOMATIC
            ):
                retry_minutes = max(
                    _TIME_RULE_OPEN_RETRY_MINUTES,
                    int(config[CONF_EVALUATION_INTERVAL]) * 2,
                )
                self._pending_time_rule_opens[cover] = now + timedelta(
                    minutes=retry_minutes
                )
                control_state_changed = True
        if control_state_changed:
            await self.async_save_control_state()

        previous_scheduled_close_covers = set(self._scheduled_close_covers)
        if workday_data_ready:
            scheduled_close_covers = {
                cover
                for cover, action in time_rule_states.items()
                if action == RULE_ACTION_CLOSE
                and cover not in self._time_rule_manual_releases
            }
        else:
            # An incomplete Workday history must not undo a previously active
            # night closure. Fresh resolvable events are still applied below and
            # the full state is reconciled as soon as Workday recovers.
            scheduled_close_covers = set(previous_scheduled_close_covers)
        for cover, action in time_rule_actions.items():
            if action == RULE_ACTION_CLOSE:
                scheduled_close_covers.add(cover)
            elif action == RULE_ACTION_OPEN:
                scheduled_close_covers.discard(cover)

        time_rule_targets = {
            cover: int(config[CONF_TIME_RULE_CLOSE_POSITION])
            for cover in scheduled_close_covers
        }
        time_rule_targets.update(
            {
                cover: int(config[CONF_OPEN_POSITION])
                for cover, action in time_rule_actions.items()
                if action == RULE_ACTION_OPEN
            }
        )
        # After an update or Home Assistant restart, reconcile every room with
        # the latest effective time-rule state. A previously elapsed opening
        # event must therefore still open its room even when it lies outside the
        # short event catch-up window. Manual overrides remain protected below.
        reconciliation_open_covers: set[str] = set()
        availability_reconciliation_covers = (
            set(self._availability_reconciliation_covers)
            if workday_data_ready
            else set()
        )
        full_time_rule_reconciliation = (
            self._startup_time_rule_reconciliation or workday_data_recovered
        )
        if full_time_rule_reconciliation or availability_reconciliation_covers:
            reconciliation_open_covers = self._select_time_rule_open_reconciliation(
                time_rule_states,
                full_reconciliation=full_time_rule_reconciliation,
                availability_covers=availability_reconciliation_covers,
            )
            time_rule_targets.update(
                {
                    cover: int(config[CONF_OPEN_POSITION])
                    for cover in reconciliation_open_covers
                }
            )
            if self.enabled and self.mode == MODE_AUTOMATIC:
                # State reconciliation after startup, Workday recovery or cover
                # availability recovery replaces a missed one-shot OPEN event.
                # Give an unavailable provider or restored backoff the same retry
                # guarantee as a freshly observed event.
                reconciliation_pending_changed = False
                retry_minutes = max(
                    _TIME_RULE_OPEN_RETRY_MINUTES,
                    int(config[CONF_EVALUATION_INTERVAL]) * 2,
                )
                open_position = int(config[CONF_OPEN_POSITION])
                for cover in reconciliation_open_covers:
                    state = self.hass.states.get(cover)
                    current = self._position_from_state(state)
                    supported = (
                        int(state.attributes.get("supported_features", 0))
                        if state is not None
                        else 0
                    )
                    effective_open_target = (
                        open_position
                        if supported & int(CoverEntityFeature.SET_POSITION)
                        else binary_cover_target(
                            open_position,
                            opening_requested=self._is_opening_request(
                                state, open_position
                            ),
                        )
                    )
                    if (
                        current is not None
                        and abs(current - effective_open_target)
                        <= POSITION_TOLERANCE
                    ):
                        continue
                    if cover not in self._pending_time_rule_opens:
                        self._pending_time_rule_opens[cover] = now + timedelta(
                            minutes=retry_minutes
                        )
                        reconciliation_pending_changed = True
                if reconciliation_pending_changed:
                    await self.async_save_control_state()
            # Consume only the recovery edges evaluated from this unchanged
            # input snapshot. A new availability transition during an awaited
            # provider/Store operation invalidates the revision and must survive
            # for the queued rerun.
            if evaluation_revision == self._input_revision:
                self._availability_reconciliation_covers.difference_update(
                    availability_reconciliation_covers
                )
        pending_open_covers = set(self._pending_time_rule_opens)
        for cover in pending_open_covers:
            scheduled_close_covers.discard(cover)
        time_rule_targets.update(
            {
                cover: int(config[CONF_OPEN_POSITION])
                for cover in pending_open_covers
            }
        )
        fresh_rule_event_covers = set(time_rule_actions)
        if self.enabled and self.mode == MODE_AUTOMATIC:
            cleared_override = False
            # Only a newly triggered schedule event may replace an older manual
            # override. Retry targets from an earlier opening event must never
            # erase a manual operation performed after that event.
            for cover in fresh_rule_event_covers:
                if self._manual_overrides.pop(cover, None) is not None:
                    self._manual_override_details.pop(cover, None)
                    cleared_override = True
            if cleared_override:
                self.data["manual_overrides"] = {
                    entity: expiry.isoformat()
                    for entity, expiry in self._manual_overrides.items()
                }
                self.data["manual_override_details"] = {
                    entity: dict(details)
                    for entity, details in self._manual_override_details.items()
                    if entity in self._manual_overrides
                }
                self._schedule_override_save()
        else:
            # Events occurring outside automatic mode are recorded but do not
            # override an explicitly selected room mode.
            time_rule_targets = {}
            scheduled_close_covers = set()

        self._scheduled_close_covers = set(scheduled_close_covers)
        stale_pending_closes = self._pending_time_rule_closes - scheduled_close_covers
        pending_close_state_changed = (
            previous_scheduled_close_covers != self._scheduled_close_covers
        )
        stale_time_rule_origins = {
            cover
            for cover, (origin, _issued_at) in self._last_command_origin.items()
            if origin == "time_rule_close" and cover not in scheduled_close_covers
        }
        for cover in stale_time_rule_origins:
            self._last_command_origin.pop(cover, None)
        if stale_time_rule_origins:
            pending_close_state_changed = True
        if stale_pending_closes:
            self._pending_time_rule_closes.difference_update(stale_pending_closes)
            for cover in stale_pending_closes:
                self._pending_time_rule_close_ready_at.pop(cover, None)
            pending_close_state_changed = True
        stale_retry_covers = set(self._pending_time_rule_close_ready_at) - scheduled_close_covers
        if stale_retry_covers:
            for cover in stale_retry_covers:
                self._pending_time_rule_close_ready_at.pop(cover, None)
            pending_close_state_changed = True
        self._schedule_time_rule_close_retry()
        if pending_close_state_changed:
            await self.async_save_control_state()

        targets: dict[str, int] = {}
        statuses: list[str] = []
        reason_code = "normal"
        reason_context: dict[str, Any] = {}

        if not self.enabled:
            status = STATUS_DISABLED
            reason_code = "control_disabled"
        elif self.mode == MODE_PAUSE:
            status = STATUS_PAUSED
            reason_code = "mode_pause"
        elif self.mode == MODE_OPEN:
            targets = {cover: int(config[CONF_OPEN_POSITION]) for cover in all_covers}
            status = STATUS_NORMAL
            reason_code = "mode_open"
        elif self.mode == MODE_CLOSED:
            targets = {cover: 0 for cover in all_covers}
            status = STATUS_NORMAL
            reason_code = "mode_closed"
        elif self.mode == MODE_HEAT_PROTECTION:
            targets = {cover: int(config[CONF_HEAT_POSITION]) for cover in all_covers}
            status = STATUS_HEAT_PROTECTION
            reason_code = "mode_heat_protection"
        else:
            targets, statuses, dynamic_status_by_cover = self._dynamic_targets(
                risk=risk,
                direct=direct,
                room_temperature=room_temperature,
                outside_temperature=outside_temperature,
                forecast_max=forecast_max,
                dynamic_daylight=dynamic_daylight,
            )
            status = self._dominant_status(statuses)
            reason_code = f"dynamic_{status}"

            # Opening time rules must never lift an already active heat
            # protection target. Such occurrences are deliberately consumed
            # and skipped instead of being retried after heat protection ends.
            time_rule_open_covers = {
                cover
                for cover, action in time_rule_actions.items()
                if action == RULE_ACTION_OPEN
            } | pending_open_covers | reconciliation_open_covers
            skipped_heat_open_covers = {
                cover
                for cover in time_rule_open_covers
                if dynamic_status_by_cover.get(cover)
                in {STATUS_HEAT_PROTECTION, STATUS_STRONG_HEAT}
            }
            if skipped_heat_open_covers:
                for cover in skipped_heat_open_covers:
                    time_rule_targets.pop(cover, None)
                    if self._pending_time_rule_opens.pop(cover, None) is not None:
                        control_state_changed = True
                reason_context["skipped_time_rule_open_covers"] = sorted(
                    skipped_heat_open_covers
                )
                if control_state_changed:
                    await self.async_save_control_state()

            if time_rule_targets:
                targets.update(time_rule_targets)
                status = STATUS_SCHEDULE
                if triggered_time_rules:
                    reason_code = "time_rule_event"
                    reason_context["rules"] = [
                        str(rule.get("name"))
                        for rule in triggered_time_rules
                        if rule.get("effective_covers")
                    ]
                elif pending_open_covers - skipped_heat_open_covers:
                    reason_code = "time_rule_open_retry"
                    reason_context["covers"] = sorted(
                        pending_open_covers - skipped_heat_open_covers
                    )
                else:
                    reason_code = "time_rule_closed"
                    reason_context["rules"] = [
                        str(rule.get("name"))
                        for rule in time_rule_state_details
                        if rule.get("action") == RULE_ACTION_CLOSE
                        and rule.get("effective_covers")
                    ]
            elif skipped_heat_open_covers:
                reason_code = "time_rule_open_skipped_heat_protection"

        weather_protection = self._weather.resolve_protection(
            now,
            outside_temperature=outside_temperature,
            wind_speed=wind_speed,
            rain_active=rain_active,
        )
        safety_covers: set[str] = set()
        if self.enabled and self.mode != MODE_PAUSE and weather_protection is not None:
            protection_kind, protection_target, protection_status = weather_protection
            self._active_weather_protection = protection_kind
            protected_targets: dict[str, int] = {}
            protection_applied: list[str] = []
            for cover in all_covers:
                requested = targets.get(cover)
                cover_state = self.hass.states.get(cover)
                if requested is not None and self._is_opening_request(
                    cover_state, int(requested)
                ):
                    # Opening and already-open targets always remain possible.
                    protected_targets[cover] = int(requested)
                    continue
                if protection_target is not None:
                    effective = max(int(requested or 0), int(protection_target))
                    protected_targets[cover] = effective
                    safety_covers.add(cover)
                    if requested is None or effective != int(requested):
                        protection_applied.append(cover)
            targets = protected_targets
            if protection_applied or protection_target is None:
                status = protection_status
                reason_code = f"{protection_kind}_protection"
                reason_context["protection_target"] = protection_target
                reason_context["covers"] = list(protection_applied)
        elif weather_protection is None or not self.enabled or self.mode == MODE_PAUSE:
            self._active_weather_protection = None

        blocked_night_close_covers: list[str] = []
        waiting_night_close_covers: list[str] = []
        pending_close_state_changed = False

        # Contacts are action-specific: they never suppress daytime solar/heat
        # shading, weather protection, explicit room modes or manual commands.
        # Only the automatic persistent close state created by a time rule is
        # held back while the assigned contact is open, tilted or unknown.
        for cover in contacts["unknown_covers"]:
            contact_entity = assignments.get(cover)
            if contact_entity:
                create_issue(
                    self.hass,
                    self.entry.entry_id,
                    "contact_unknown",
                    entity_id=contact_entity,
                    placeholders={"entity": contact_entity, "room": self.room_name},
                    severity=ir.IssueSeverity.WARNING,
                )
        for cover in (
            contacts["closed_covers"]
            + contacts["open_covers"]
            + contacts["tilted_covers"]
        ):
            contact_entity = assignments.get(cover)
            if contact_entity:
                delete_issue(
                    self.hass, self.entry.entry_id, "contact_unknown", contact_entity
                )

        if self.enabled and self.mode == MODE_AUTOMATIC:
            for cover in scheduled_close_covers:
                contact_info = contacts["by_cover"].get(cover, {})
                contact_state = contact_info.get("state")
                if contact_state not in {
                    CONTACT_OPEN,
                    CONTACT_TILTED,
                    CONTACT_UNKNOWN,
                    CONTACT_CLOSED,
                }:
                    # No contact assigned: the night rule remains unrestricted.
                    continue

                requested = targets.get(cover)
                cover_state = self.hass.states.get(cover)
                if requested is None or self._is_opening_request(
                    cover_state, int(requested)
                ):
                    continue

                previous_pending = cover in self._pending_time_rule_closes
                previous_retry = self._pending_time_rule_close_ready_at.get(cover)
                block_close, keep_pending, retry_at = resolve_night_close_contact(
                    contact_state,
                    pending=previous_pending,
                    retry_at=previous_retry,
                    now=now,
                    delay_seconds=_TIME_RULE_CLOSE_CONTACT_DELAY_SECONDS,
                )
                if keep_pending:
                    self._pending_time_rule_closes.add(cover)
                else:
                    self._pending_time_rule_closes.discard(cover)
                if retry_at is None:
                    self._pending_time_rule_close_ready_at.pop(cover, None)
                else:
                    self._pending_time_rule_close_ready_at[cover] = retry_at
                if (
                    previous_pending != keep_pending
                    or previous_retry != retry_at
                ):
                    pending_close_state_changed = True
                if block_close and contact_state == CONTACT_CLOSED:
                    waiting_night_close_covers.append(cover)

                if block_close:
                    # A blocked night rule must not manufacture an opening
                    # command during startup or provider recovery. Unknown,
                    # unavailable and the post-close debounce window only
                    # suppress the automatic close target and preserve the
                    # shutter's current physical position. A real transition
                    # from closed to open/tilted is handled by the contact
                    # event callback and may then release a prior night close.
                    targets.pop(cover, None)
                    blocked_night_close_covers.append(cover)

        self._schedule_time_rule_close_retry()
        if pending_close_state_changed:
            await self.async_save_control_state()

        if blocked_night_close_covers:
            status = STATUS_CONTACT_PROTECTION
            if waiting_night_close_covers and len(waiting_night_close_covers) == len(
                blocked_night_close_covers
            ):
                reason_code = "time_rule_close_contact_delay"
            else:
                reason_code = "time_rule_close_blocked_contact"
            reason_context.update(
                {
                    "covers": sorted(blocked_night_close_covers),
                    "waiting_after_contact_close": sorted(waiting_night_close_covers),
                    "delay_seconds": _TIME_RULE_CLOSE_CONTACT_DELAY_SECONDS,
                }
            )

        allowed_scheduled_close_covers = (
            scheduled_close_covers - set(blocked_night_close_covers)
        )
        for cover, details in contacts["by_cover"].items():
            details["night_close_active"] = cover in scheduled_close_covers
            details["night_close_blocked"] = cover in blocked_night_close_covers
            retry_at = self._pending_time_rule_close_ready_at.get(cover)
            details["night_close_retry_at"] = (
                retry_at.isoformat() if retry_at is not None else None
            )
        contacts["pending_night_close_covers"] = sorted(
            self._pending_time_rule_closes
        )
        contacts["night_close_delay_seconds"] = (
            _TIME_RULE_CLOSE_CONTACT_DELAY_SECONDS
        )

        desired_positions = dict(targets)

        skipped_manual: list[str] = []
        for cover in list(targets):
            if cover in safety_covers:
                continue
            if cover in self._manual_overrides:
                skipped_manual.append(cover)
                del targets[cover]
        if skipped_manual and not targets:
            status = STATUS_MANUAL_OVERRIDE
            reason_code = "all_manual_override"
            reason_context["covers"] = list(skipped_manual)
        elif skipped_manual:
            reason_context["manual_override_covers"] = list(skipped_manual)

        if not self._started:
            return

        effective_targets = dict(targets)
        if targets and self.enabled and self.mode != MODE_PAUSE:
            effective_targets = await self._async_apply_targets(
                targets,
                force=force,
                safety_covers=safety_covers,
                # A newly triggered rule may bypass the normal movement
                # throttle. Restored pending/startup reconciliation is a
                # recalculation and must retain the original cooldown.
                forced_covers=fresh_rule_event_covers,
                time_rule_close_covers=allowed_scheduled_close_covers,
                evaluation_revision=evaluation_revision,
            )

        pending_open_completed = False
        if (
            pending_open_covers
            and self.enabled
            and self.mode == MODE_AUTOMATIC
        ):
            open_position = int(config[CONF_OPEN_POSITION])
            dry_run = normalize_boolean(config.get(CONF_DRY_RUN), False)
            for cover in pending_open_covers:
                state = self.hass.states.get(cover)
                current = self._position_from_state(state)
                supported = (
                    int(state.attributes.get("supported_features", 0))
                    if state is not None
                    else 0
                )
                effective_open_target = (
                    open_position
                    if supported & int(CoverEntityFeature.SET_POSITION)
                    else binary_cover_target(
                        open_position,
                        opening_requested=self._is_opening_request(
                            state, open_position
                        ),
                    )
                )
                reached = (
                    current is not None
                    and abs(current - effective_open_target) <= POSITION_TOLERANCE
                )
                if (
                    dry_run or cover in effective_targets or reached
                ) and self._pending_time_rule_opens.pop(cover, None) is not None:
                    pending_open_completed = True
            if pending_open_completed:
                await self.async_save_control_state()

        if (
            not self._transient_command_failure
            and self._provider_command_attempted
            and self._provider_command_succeeded
        ):
            self._reset_provider_recovery_state()

        cover_states = {cover: self.hass.states.get(cover) for cover in all_covers}
        actual_positions = {
            cover: self._position_from_state(state)
            for cover, state in cover_states.items()
        }
        actual_tilt_positions = {
            cover: self._tilt_position_from_state(state)
            for cover, state in cover_states.items()
        }
        for cover, state in cover_states.items():
            if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
                continue
            position = actual_positions[cover]
            if position is not None:
                self._last_known_positions[cover] = position
                pending = self._pending_command_targets.get(cover)
                if (
                    pending is not None
                    and abs(position - pending[0]) <= POSITION_TOLERANCE
                ):
                    self._pending_command_targets.pop(cover, None)
            tilt_position = actual_tilt_positions[cover]
            if tilt_position is not None:
                self._last_known_tilt_positions[cover] = tilt_position
                pending_tilt = self._pending_tilt_targets.get(cover)
                if (
                    pending_tilt is not None
                    and abs(tilt_position - pending_tilt[0]) <= POSITION_TOLERANCE
                ):
                    self._pending_tilt_targets.pop(cover, None)
        decision_trace = [
            {
                "cover": cover,
                "desired_position": desired_positions.get(cover),
                "commanded_position": effective_targets.get(cover),
                "actual_position": actual_positions.get(cover),
                "contact_state": contacts["by_cover"].get(cover, {}).get("state"),
                "manual_override": cover in self._manual_overrides,
                "safety_forced": cover in safety_covers,
                "night_close_active": cover in scheduled_close_covers,
                "night_close_blocked": cover in blocked_night_close_covers,
            }
            for cover in all_covers
        ]
        if normalize_boolean(config.get(CONF_DRY_RUN), False) and targets:
            reason_context["underlying_reason_code"] = reason_code
            status = STATUS_DRY_RUN
            reason_code = "dry_run"
        self._append_decision(
            now,
            status,
            reason_code,
            desired_positions,
            effective_targets,
            actual_positions,
        )
        queue_snapshot = self._command_queue.snapshot()
        self.data.update(
            status=status,
            reason=reason_code,
            reason_code=reason_code,
            reason_context=reason_context,
            decision_trace=decision_trace,
            dry_run=normalize_boolean(config.get(CONF_DRY_RUN), False),
            would_command_positions=(effective_targets if normalize_boolean(config.get(CONF_DRY_RUN), False) else {}),
            heat_risk=risk,
            sun_load=round(sun_load * 100),
            direct_sun=any(direct.values()),
            direct_sun_by_orientation=direct,
            sun_incidence_by_orientation=incidence,
            effective_position_settings={
                key: int(config[key]) for key in POSITION_SETTING_KEYS
            },
            desired_positions=desired_positions,
            commanded_positions=effective_targets,
            actual_positions=actual_positions,
            actual_tilt_positions=actual_tilt_positions,
            time_rule_manual_releases=sorted(self._time_rule_manual_releases),
            pending_time_rule_opens={
                entity: expiry.isoformat()
                for entity, expiry in self._pending_time_rule_opens.items()
            },
            pending_time_rule_closes={
                entity: {
                    "retry_at": (
                        self._pending_time_rule_close_ready_at[entity].isoformat()
                        if entity in self._pending_time_rule_close_ready_at
                        else None
                    ),
                    "contact_state": contacts["by_cover"].get(entity, {}).get(
                        "state"
                    ),
                }
                for entity in sorted(self._pending_time_rule_closes)
            },
            manual_overrides={
                entity: expiry.isoformat()
                for entity, expiry in self._manual_overrides.items()
            },
            contacts=contacts,
            last_time_rule_event=(
                triggered_time_rules[0]
                if triggered_time_rules
                else self.data.get("last_time_rule_event")
            ),
            triggered_time_rules=triggered_time_rules,
            time_rule_states=time_rule_state_details,
            room_temperature=room_temperature,
            outside_temperature=outside_temperature,
            forecast_max=forecast_max,
            temperature_trend=round(trend, 2),
            weather_condition=condition,
            weather_factor=round(radiation, 3),
            wind_speed=wind_speed,
            rain_active=rain_active,
            active_weather_protection=self._active_weather_protection,
            provider_health={
                "state": "degraded" if self._provider_failures else "ok",
                "consecutive_failures": self._provider_failures,
                "retry_attempt": self._command_retry_attempts,
            },
            provider_failures=self._provider_failures,
            command_queue=queue_snapshot,
            command_queue_depth=int(queue_snapshot.get("depth", 0)),
            command_queue_busy=bool(queue_snapshot.get("busy")),
            pending_time_rule_open_count=len(self._pending_time_rule_opens),
            pending_time_rule_close_count=len(self._pending_time_rule_closes),
            next_time_rule_close_retry=(
                self._time_rule_close_retry_at.isoformat()
                if self._time_rule_close_retry_at is not None
                else None
            ),
            provider_health_by_cover={
                entity: dict(health)
                for entity, health in self._provider_health_by_cover.items()
            },
            is_workday=is_workday,
            workday_data_ready=workday_data_ready,
            sun_azimuth=sun_azimuth,
            sun_elevation=sun_elevation,
            sun_above_horizon=sun_above_horizon,
            dynamic_daylight=dynamic_daylight,
            sun_entity=str(config.get(CONF_SUN_ENTITY) or "sun.sun"),
            facade_azimuths=calculated_facade_azimuths,
            last_evaluation=now.isoformat(),
        )
        if runtime_state_before != self._runtime_storage_state():
            await self.async_save_control_state()
        self._publish()

    def _dynamic_targets(
        self,
        *,
        risk: int,
        direct: dict[str, bool],
        room_temperature: float | None,
        outside_temperature: float | None,
        forecast_max: float | None,
        dynamic_daylight: bool,
    ) -> tuple[dict[str, int], list[str], dict[str, str]]:
        config = self.config
        targets: dict[str, int] = {}
        statuses: list[str] = []
        status_by_cover: dict[str, str] = {}

        if not dynamic_daylight:
            return targets, [STATUS_NORMAL], status_by_cover

        for orientation, covers in self.covers_by_orientation.items():
            if not covers:
                continue

            previous = self._previous_level.get(orientation)
            level = choose_dynamic_level(
                risk,
                previous,
                int(config[CONF_RISK_HYSTERESIS]),
            )

            solar_gain = direct[orientation] and allow_solar_gain(
                risk=risk,
                room_temperature=room_temperature,
                outside_temperature=outside_temperature,
                forecast_max=forecast_max,
                comfort_temperature=float(config[CONF_COMFORT_TEMPERATURE]),
                forecast_threshold=float(config[CONF_FORECAST_THRESHOLD]),
            )

            if solar_gain:
                target = int(config[CONF_OPEN_POSITION])
                status = STATUS_SOLAR_GAIN
                effective_level = "normal"
            elif direct[orientation]:
                effective_level = level
                if (
                    room_temperature is not None
                    and room_temperature >= float(config[CONF_STRONG_HEAT_TEMPERATURE])
                ):
                    effective_level = "strong"
                elif (
                    room_temperature is not None
                    and room_temperature >= float(config[CONF_HEAT_TEMPERATURE])
                    and effective_level == "preventive"
                ):
                    effective_level = "heat"

                if effective_level == "strong":
                    target = int(config[CONF_STRONG_HEAT_POSITION])
                    status = STATUS_STRONG_HEAT
                elif effective_level == "heat":
                    target = int(config[CONF_HEAT_POSITION])
                    status = STATUS_HEAT_PROTECTION
                elif effective_level == "preventive":
                    target = int(config[CONF_PREVENTIVE_POSITION])
                    status = STATUS_PREVENTIVE
                else:
                    target = int(config[CONF_OPEN_POSITION])
                    status = STATUS_NORMAL
            else:
                target = int(config[CONF_OPEN_POSITION])
                status = STATUS_NORMAL
                effective_level = "normal"

            self._previous_level[orientation] = effective_level
            for cover in covers:
                targets[cover] = target
                status_by_cover[cover] = status
            statuses.append(status)

        return targets, statuses, status_by_cover

    def _dominant_status(self, statuses: list[str]) -> str:
        priority = [
            STATUS_STRONG_HEAT,
            STATUS_HEAT_PROTECTION,
            STATUS_PREVENTIVE,
            STATUS_SOLAR_GAIN,
            STATUS_NORMAL,
        ]
        for status in priority:
            if status in statuses:
                return status
        return STATUS_NORMAL

    async def _async_apply_targets(
        self,
        targets: dict[str, int],
        force: bool,
        safety_covers: set[str] | None = None,
        forced_covers: set[str] | None = None,
        time_rule_close_covers: set[str] | None = None,
        evaluation_revision: int | None = None,
    ) -> dict[str, int]:
        """Apply targets and return only positions actually commanded.

        Covers without SET_POSITION can only be fully opened or closed. Their
        requested percentage is quantized before tolerance and move-interval
        checks. Separate effective targets are retained for independent slat
        control even when no vertical command is necessary.
        """
        now = dt_util.utcnow()
        config = self.config
        min_change = int(config[CONF_MIN_POSITION_CHANGE])
        min_interval = timedelta(minutes=int(config[CONF_MIN_MOVE_INTERVAL]))
        tilt_source_targets: dict[str, int] = {}
        commanded_targets: dict[str, int] = {}
        dry_run = normalize_boolean(config.get(CONF_DRY_RUN), False)
        forced_safety_covers = safety_covers or set()
        forced_rule_covers = forced_covers or set()
        scheduled_close_origins = time_rule_close_covers or set()

        for entity_id, raw_target in targets.items():
            if (
                not self._started
                or not self.enabled
                or self.mode == MODE_PAUSE
                or (
                    evaluation_revision is not None
                    and evaluation_revision != self._input_revision
                )
            ):
                break
            requested_target = int(clamp(float(raw_target), 0.0, 100.0))
            state = self.hass.states.get(entity_id)
            if state is None or state.state in {STATE_UNAVAILABLE, STATE_UNKNOWN}:
                continue

            tilt_source_targets[entity_id] = requested_target
            supported = int(state.attributes.get("supported_features", 0))
            supports_position = bool(
                supported & int(CoverEntityFeature.SET_POSITION)
            )
            cover_is_safety_forced = entity_id in forced_safety_covers
            current = self._position_from_state(state)
            if (
                current is not None
                and abs(current - requested_target) <= POSITION_TOLERANCE
            ):
                # Compare the requested percentage before binary quantization.
                # Otherwise an already reached 40-percent target could be
                # transformed into OPEN and trigger an unnecessary movement.
                continue
            opening_requested = self._is_opening_request(state, requested_target)
            target = (
                requested_target
                if supports_position
                else binary_cover_target(
                    requested_target,
                    safety_forced=cover_is_safety_forced,
                    opening_requested=opening_requested,
                )
            )
            last_command = self._last_command.get(entity_id)
            if (
                last_command is not None
                and last_command[0] == target
                and (now - last_command[1]).total_seconds()
                <= COMMAND_GRACE_SECONDS
            ):
                continue

            cover_force = (
                (force and not self._startup_time_rule_reconciliation)
                or cover_is_safety_forced
                or entity_id in forced_rule_covers
            )
            last_move = self._last_move.get(entity_id)
            if current is not None and abs(current - target) <= POSITION_TOLERANCE:
                continue
            if (
                current is None
                and state.state in {"opening", "closing"}
                and not cover_force
            ):
                continue
            if not cover_force:
                if current is not None and abs(current - target) < min_change:
                    continue
                if last_move and now - last_move < min_interval:
                    continue

            if dry_run:
                commanded_targets[entity_id] = target
                continue
            if await self._async_move_cover(
                entity_id,
                state,
                target,
                evaluation_revision=evaluation_revision,
                bypass_manual_override=cover_is_safety_forced,
                bypass_provider_backoff=(
                    cover_is_safety_forced
                    or (force and not self._startup_time_rule_reconciliation)
                ),
                priority=(
                    PRIORITY_SAFETY
                    if cover_is_safety_forced
                    else PRIORITY_AUTOMATIC
                ),
                origin=(
                    "time_rule_close"
                    if entity_id in scheduled_close_origins
                    else "automatic"
                ),
            ):
                commanded_targets[entity_id] = target
                self._last_move[entity_id] = now
            else:
                # Do not apply a tilt profile for a vertical target that the
                # provider rejected. That would leave the cover in a mixed,
                # diagnostically misleading state.
                tilt_source_targets.pop(entity_id, None)

        if commanded_targets and not dry_run:
            # Store the per-cover cooldown immediately after provider success;
            # a reload must not create a window for an early second movement.
            await self.async_save_control_state()

        tilt_targets = await self._async_apply_tilt_targets(
            tilt_source_targets,
            forced_safety_covers,
            dry_run=dry_run,
            evaluation_revision=evaluation_revision,
        )
        self.data["commanded_tilt_positions"] = tilt_targets
        self.data["would_command_tilt_positions"] = tilt_targets if dry_run else {}
        return commanded_targets

    async def _async_apply_tilt_targets(
        self,
        position_targets: dict[str, int],
        safety_covers: set[str],
        *,
        dry_run: bool,
        evaluation_revision: int | None = None,
    ) -> dict[str, int]:
        """Apply slat tilt independently through the room-owned command queue."""
        config = self.config
        if not normalize_boolean(config.get(CONF_TILT_CONTROL_ENABLED), False):
            return {}
        now = dt_util.utcnow()
        result: dict[str, int] = {}

        def evaluation_is_valid() -> bool:
            return bool(
                self._started
                and self.enabled
                and self.mode != MODE_PAUSE
                and (
                    evaluation_revision is None
                    or evaluation_revision == self._input_revision
                )
            )

        for entity_id, position_target in position_targets.items():
            if not evaluation_is_valid():
                break
            cover_is_safety_forced = entity_id in safety_covers

            def command_is_valid(
                *,
                cover_entity: str = entity_id,
                bypass_protection: bool = cover_is_safety_forced,
            ) -> bool:
                """Revalidate per-cover protection immediately before service."""
                current_time = dt_util.utcnow()
                override_expiry = self._manual_overrides.get(cover_entity)
                override_active = bool(
                    override_expiry is not None and override_expiry > current_time
                )
                retry_active = bool(
                    self._command_retry_at is not None
                    and self._command_retry_at > current_time
                )
                return bool(
                    evaluation_is_valid()
                    and (bypass_protection or not override_active)
                    and (bypass_protection or not retry_active)
                )

            # Dry-run diagnostics deliberately show the calculated action and
            # never reach the provider. Real automatic tilt calls obey the same
            # restored manual and provider-backoff guards as vertical calls.
            if not dry_run and not command_is_valid():
                continue
            state = self.hass.states.get(entity_id)
            if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
                continue
            supported = int(state.attributes.get("supported_features", 0))
            supports_set = bool(supported & int(CoverEntityFeature.SET_TILT_POSITION))
            supports_open = bool(supported & int(CoverEntityFeature.OPEN_TILT))
            supports_close = bool(supported & int(CoverEntityFeature.CLOSE_TILT))
            if cover_is_safety_forced:
                target = int(config[CONF_TILT_SAFETY_POSITION])
            elif position_target <= int(config[CONF_STRONG_HEAT_POSITION]):
                target = int(config[CONF_TILT_STRONG_HEAT_POSITION])
            elif position_target <= int(config[CONF_HEAT_POSITION]):
                target = int(config[CONF_TILT_HEAT_POSITION])
            else:
                target = int(config[CONF_TILT_DEFAULT_POSITION])
            target = max(0, min(100, target))
            if not supports_set:
                target = 0 if target <= 50 else 100
                required_supported = supports_close if target == 0 else supports_open
                if not required_supported:
                    create_issue(
                        self.hass,
                        self.entry.entry_id,
                        "cover_tilt_unsupported",
                        entity_id=entity_id,
                        placeholders={"entity": entity_id, "room": self.room_name},
                        severity=ir.IssueSeverity.WARNING,
                    )
                    continue
            delete_issue(
                self.hass, self.entry.entry_id, "cover_tilt_unsupported", entity_id
            )
            current = self._tilt_position_from_state(state)
            if current is not None and abs(current - target) <= POSITION_TOLERANCE:
                continue
            vertical_current = self._position_from_state(state)
            recent_vertical = self._last_command.get(entity_id)
            vertical_target_pending = (
                recent_vertical is not None
                and (now - recent_vertical[1]).total_seconds() <= COMMAND_GRACE_SECONDS
                and (
                    vertical_current is None
                    or abs(vertical_current - recent_vertical[0]) > POSITION_TOLERANCE
                )
            )
            if not dry_run and (
                state.state in {"opening", "closing"} or vertical_target_pending
            ):
                continue
            last = self._last_tilt_command.get(entity_id)
            if (
                last
                and last[0] == target
                and (now - last[1]).total_seconds() <= COMMAND_GRACE_SECONDS
            ):
                continue
            if dry_run:
                result[entity_id] = target
                continue

            if supports_set:
                service = "set_cover_tilt_position"
                service_data = {ATTR_TILT_POSITION: target}
            elif target <= 50:
                service = "close_cover_tilt"
                service_data = {}
            else:
                service = "open_cover_tilt"
                service_data = {}

            context = Context()

            def command_started(
                started_context: Context,
                issued_at: datetime,
                *,
                cover_entity: str = entity_id,
                commanded_target: int = target,
            ) -> None:
                self._command_contexts[started_context.id] = issued_at + timedelta(
                    seconds=COMMAND_GRACE_SECONDS
                )
                self._command_context_covers[started_context.id] = cover_entity
                self._last_tilt_command[cover_entity] = (
                    commanded_target,
                    issued_at,
                )
                self._pending_tilt_targets[cover_entity] = (
                    commanded_target,
                    issued_at + _PENDING_TARGET_HORIZON,
                )
                self._create_entry_task(
                    self.async_save_control_state(), "persist tilt command marker"
                )

            self._provider_command_attempted = True
            queue_result = await self._command_queue.async_submit(
                entity_id=entity_id,
                command_type="tilt",
                service=service,
                service_data=service_data,
                priority=(
                    PRIORITY_SAFETY if cover_is_safety_forced else PRIORITY_TILT
                ),
                coalesce_key="tilt",
                context=context,
                is_valid=command_is_valid,
                on_started=command_started,
            )
            if (
                not queue_result.success
                and queue_result.issued_at is not None
                and queue_result.context_id
            ):
                self._command_contexts.pop(queue_result.context_id, None)
                self._command_context_covers.pop(queue_result.context_id, None)
                if self._last_tilt_command.get(entity_id) == (
                    target,
                    queue_result.issued_at,
                ):
                    self._last_tilt_command.pop(entity_id, None)
                if self._pending_tilt_targets.get(entity_id) == (
                    target,
                    queue_result.issued_at + _PENDING_TARGET_HORIZON,
                ):
                    self._pending_tilt_targets.pop(entity_id, None)
                self._create_entry_task(
                    self.async_save_control_state(),
                    "remove failed tilt command marker",
                )
            if self._handle_command_result(
                entity_id,
                queue_result,
                log_message=f"Could not set tilt for %s to {target}",
            ):
                result[entity_id] = target
        if result and not dry_run:
            await self.async_save_control_state()
        return result

    def _forget_failed_command(
        self,
        entity_id: str,
        context_id: str,
        target: int,
        issued_at: datetime,
    ) -> None:
        """Remove command markers when the service call did not complete."""
        self._command_contexts.pop(context_id, None)
        self._command_context_covers.pop(context_id, None)
        if self._last_command.get(entity_id) == (target, issued_at):
            self._last_command.pop(entity_id, None)
        if self._pending_command_targets.get(entity_id) == (
            target,
            issued_at + _PENDING_TARGET_HORIZON,
        ):
            self._pending_command_targets.pop(entity_id, None)
        origin = self._last_command_origin.get(entity_id)
        if origin is not None and origin[1] == issued_at:
            self._last_command_origin.pop(entity_id, None)
        self._create_entry_task(
            self.async_save_control_state(), "remove failed command marker"
        )

    async def _async_move_cover(
        self,
        entity_id: str,
        state: State,
        target: int,
        *,
        evaluation_revision: int | None = None,
        manual: bool = False,
        manual_revision: int | None = None,
        bypass_manual_override: bool = False,
        bypass_provider_backoff: bool = False,
        priority: int | None = None,
        origin: str | None = None,
    ) -> bool:
        """Move one cover through the coalescing provider command queue."""
        def command_is_valid() -> bool:
            override_expiry = self._manual_overrides.get(entity_id)
            override_active = bool(
                override_expiry is not None
                and override_expiry > dt_util.utcnow()
            )
            retry_active = bool(
                self._command_retry_at is not None
                and self._command_retry_at > dt_util.utcnow()
            )
            return bool(
                self._started
                and (manual or self.enabled)
                and (manual or self.mode != MODE_PAUSE)
                and (
                    manual
                    or bypass_manual_override
                    or not override_active
                )
                and (manual or bypass_provider_backoff or not retry_active)
                and (
                    evaluation_revision is None
                    or evaluation_revision == self._input_revision
                )
                and (
                    manual_revision is None
                    or manual_revision == self._manual_command_revision
                )
            )

        if not command_is_valid():
            return False
        if normalize_boolean(self.config.get(CONF_DRY_RUN), False):
            return True

        supported = int(state.attributes.get("supported_features", 0))
        if supported & int(CoverEntityFeature.SET_POSITION):
            service = "set_cover_position"
            service_data = {ATTR_POSITION: target}
        elif target <= 50:
            service = "close_cover"
            service_data = {}
        else:
            service = "open_cover"
            service_data = {}

        context = Context()

        command_origin = str(origin or ("manual" if manual else "automatic"))

        def command_started(started_context: Context, issued_at: datetime) -> None:
            self._command_contexts[started_context.id] = issued_at + timedelta(
                seconds=COMMAND_GRACE_SECONDS
            )
            self._command_context_covers[started_context.id] = entity_id
            self._last_command[entity_id] = (target, issued_at)
            self._pending_command_targets[entity_id] = (
                target,
                issued_at + _PENDING_TARGET_HORIZON,
            )
            self._last_command_origin[entity_id] = (command_origin, issued_at)
            self._create_entry_task(
                self.async_save_control_state(), "persist command marker"
            )

        self._provider_command_attempted = True
        result = await self._command_queue.async_submit(
            entity_id=entity_id,
            command_type="vertical",
            service=service,
            service_data=service_data,
            priority=(
                int(priority)
                if priority is not None
                else PRIORITY_MANUAL if manual else PRIORITY_AUTOMATIC
            ),
            coalesce_key="vertical",
            context=context,
            is_valid=command_is_valid,
            on_started=command_started,
        )
        if not result.success and result.issued_at is not None and result.context_id:
            self._forget_failed_command(
                entity_id, result.context_id, target, result.issued_at
            )
        return self._handle_command_result(
            entity_id,
            result,
            log_message=f"Could not move cover %s to {target}",
        )

    async def _async_refresh_forecast_if_needed(self, now: datetime) -> None:
        """Use fresh shared forecast data without leaking an old provider."""
        coordinator = self.coordinator
        weather_entity = self.config.get(CONF_WEATHER_ENTITY)
        normalized_source = str(weather_entity or "") or None
        same_persisted_source = self._forecast_source == normalized_source
        forecast: list[dict[str, Any]] = (
            [dict(item) for item in self._forecast]
            if same_persisted_source
            else []
        )
        updated_at: datetime | None = (
            self._forecast_updated if same_persisted_source else None
        )
        forecast_type = self._forecast_type if same_persisted_source else None
        if coordinator is not None:
            coordinated_entity = (coordinator.data or {}).get("weather_entity")
            source_changed = str(coordinated_entity or "") != str(weather_entity or "")
            if source_changed:
                coordinator.update_config(coordinator.entry, self.config)
                await coordinator.async_ensure_ready(force=True)
            elif (coordinator.data or {}).get("last_error_retryable"):
                weather_state = (
                    self.hass.states.get(str(weather_entity))
                    if weather_entity
                    else None
                )
                if weather_state is not None and weather_state.state not in {
                    STATE_UNKNOWN,
                    STATE_UNAVAILABLE,
                }:
                    await coordinator.async_ensure_ready(force=True)
            coordinated_forecast = list(coordinator.forecast)
            retryable_failure = bool(
                (coordinator.data or {}).get("last_error_retryable")
            )
            # On a cold restart, retain only a fresh persisted forecast from
            # this exact provider while its first refresh is transiently
            # unavailable. A successful empty response intentionally clears it.
            if coordinated_forecast or not retryable_failure:
                forecast = coordinated_forecast
                raw_type = (coordinator.data or {}).get("forecast_type")
                forecast_type = str(raw_type) if raw_type else None
                updated = (coordinator.data or {}).get("forecast_updated")
                updated_at = (
                    dt_util.parse_datetime(str(updated)) if updated else None
                )
                if updated_at is not None:
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=dt_util.UTC)
                    updated_at = dt_util.as_utc(updated_at)

        age_minutes: float | None = None
        if updated_at is not None:
            age_minutes = max(
                0.0,
                (dt_util.as_utc(now) - updated_at).total_seconds() / 60.0,
            )
        forecast_stale = bool(forecast) and (
            updated_at is None or age_minutes is None
            or age_minutes > _FORECAST_STALE_MINUTES
        )
        self._forecast = [] if forecast_stale else forecast
        self._forecast_updated = None if forecast_stale else updated_at
        self._forecast_type = None if forecast_stale else forecast_type
        self._forecast_source = normalized_source
        self.data.update(
            forecast_updated=(
                self._forecast_updated.isoformat()
                if self._forecast_updated is not None
                else None
            ),
            forecast_age_minutes=(
                round(age_minutes, 1) if age_minutes is not None else None
            ),
            forecast_stale=forecast_stale,
            forecast_type=self._forecast_type,
        )

    def _update_repairs(self, covers: list[str]) -> None:
        """Maintain room Repairs and delegate central settings exactly once."""
        config = self.config
        coordinator = self.coordinator
        if coordinator is not None:
            update_global_repairs(
                self.hass,
                coordinator.entry,
                coordinator.config,
                forecast_error=(
                    str((coordinator.data or {}).get("last_error") or "") or None
                ),
            )

        watched_entities = set(self._room_repair_entities())
        delete_stale_entity_issues(
            self.hass, self.entry.entry_id, watched_entities
        )
        entity_registry = er.async_get(self.hass)
        for entity_id in watched_entities:
            state = self.hass.states.get(entity_id)
            registry_entry = entity_registry.async_get(entity_id)
            # A state can be absent temporarily while its owning integration is
            # starting or retrying. Only report a genuinely missing entity when
            # neither the state machine nor the entity registry knows it.
            if state is None and registry_entry is None:
                create_issue(
                    self.hass,
                    self.entry.entry_id,
                    "missing_entity",
                    entity_id=entity_id,
                    placeholders={"entity": entity_id, "room": self.room_name},
                )
            else:
                delete_issue(
                    self.hass, self.entry.entry_id, "missing_entity", entity_id
                )

        partial_targets = {
            int(config[CONF_OPEN_POSITION]),
            int(config[CONF_PREVENTIVE_POSITION]),
            int(config[CONF_HEAT_POSITION]),
            int(config[CONF_STRONG_HEAT_POSITION]),
            int(config[CONF_WIND_SAFE_POSITION]),
            int(config[CONF_STORM_SAFE_POSITION]),
            int(config[CONF_RAIN_SAFE_POSITION]),
            int(config[CONF_FROST_SAFE_POSITION]),
        } - {0, 100}
        for cover in covers:
            state = self.hass.states.get(cover)
            if state is None:
                continue
            supported = int(state.attributes.get("supported_features", 0))
            # Emergency-stop support is only actionable while a stop is
            # currently required; remove any issue left from an older event.
            delete_issue(
                self.hass, self.entry.entry_id, "cover_stop_unsupported", cover
            )
            if normalize_boolean(config.get(CONF_TILT_CONTROL_ENABLED), False):
                supports_set_tilt = bool(
                    supported & int(CoverEntityFeature.SET_TILT_POSITION)
                )
                supports_open_tilt = bool(
                    supported & int(CoverEntityFeature.OPEN_TILT)
                )
                supports_close_tilt = bool(
                    supported & int(CoverEntityFeature.CLOSE_TILT)
                )
                configured_tilt_targets = {
                    int(config[CONF_TILT_DEFAULT_POSITION]),
                    int(config[CONF_TILT_HEAT_POSITION]),
                    int(config[CONF_TILT_STRONG_HEAT_POSITION]),
                    int(config[CONF_TILT_SAFETY_POSITION]),
                }
                tilt_supported = supports_set_tilt or all(
                    supports_close_tilt if target <= 50 else supports_open_tilt
                    for target in configured_tilt_targets
                )
                if not tilt_supported:
                    create_issue(
                        self.hass,
                        self.entry.entry_id,
                        "cover_tilt_unsupported",
                        entity_id=cover,
                        placeholders={"entity": cover, "room": self.room_name},
                        severity=ir.IssueSeverity.WARNING,
                    )
                else:
                    delete_issue(
                        self.hass,
                        self.entry.entry_id,
                        "cover_tilt_unsupported",
                        cover,
                    )
            else:
                delete_issue(
                    self.hass, self.entry.entry_id, "cover_tilt_unsupported", cover
                )

            if partial_targets and not bool(
                supported & int(CoverEntityFeature.SET_POSITION)
            ):
                create_issue(
                    self.hass,
                    self.entry.entry_id,
                    "cover_position_unsupported",
                    entity_id=cover,
                    placeholders={"entity": cover, "room": self.room_name},
                    severity=ir.IssueSeverity.WARNING,
                )
            else:
                delete_issue(
                    self.hass, self.entry.entry_id, "cover_position_unsupported", cover
                )

    def _record_temperature(self, now: datetime, value: float | None) -> None:
        if value is None:
            return
        if not self._temperature_samples:
            self._temperature_samples.append((now, value))
            return
        last_time, last_value = self._temperature_samples[-1]
        if now - last_time >= timedelta(minutes=5) or abs(value - last_value) >= 0.1:
            self._temperature_samples.append((now, value))
        cutoff = now - timedelta(hours=2)
        while self._temperature_samples and self._temperature_samples[0][0] < cutoff:
            self._temperature_samples.popleft()

    def _temperature_trend(self) -> float:
        if len(self._temperature_samples) < 2:
            return 0.0
        first_time, first_value = self._temperature_samples[0]
        last_time, last_value = self._temperature_samples[-1]
        hours = (last_time - first_time).total_seconds() / 3600.0
        if hours < 0.25:
            return 0.0
        return (last_value - first_value) / hours

    async def _async_prepare_workday_dates(
        self,
        local_now: datetime,
        rules: list[dict[str, Any]],
        entity_id: str | None,
        current_state: bool | None,
    ) -> None:
        """Delegate Workday date checks to the shared coordinator."""
        coordinator = self.coordinator
        if coordinator is None:
            return
        await coordinator.async_prepare_workday_dates(
            local_now,
            rules,
            entity_id,
            current_state,
            CONF_RULE_DAY_TYPE,
            DAY_TYPE_ANY,
        )

    def _workday_for_date(self, target_date: date) -> bool | None:
        """Return a shared cached Workday result for an event calendar date."""
        coordinator = self.coordinator
        if coordinator is None:
            return None
        return coordinator.workday_for_date(
            str(self.config.get(CONF_WORKDAY_ENTITY) or "") or None,
            target_date,
        )

    def _workday_history_ready(
        self,
        local_now: datetime,
        rules: list[dict[str, Any]],
        entity_id: str | None,
    ) -> bool:
        """Return whether day-type rules have a complete decision horizon."""
        if not any(
            str(rule.get(CONF_RULE_DAY_TYPE) or DAY_TYPE_ANY) != DAY_TYPE_ANY
            for rule in rules
        ):
            return True
        if not entity_id:
            return False
        # Schedule-state resolution looks back eight days; solar offsets may
        # cross either adjacent calendar boundary.
        return all(
            self._workday_for_date(local_now.date() + timedelta(days=delta))
            is not None
            for delta in range(-9, 2)
        )

    def _workday_state(self, entity_id: str | None) -> bool | None:
        """Return the state of the optional central Workday binary sensor."""
        if not entity_id:
            return None
        state = self.hass.states.get(str(entity_id))
        if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
            return None
        if state.state == "on":
            return True
        if state.state == "off":
            return False
        return None

    def _temperature_state(
        self, entity_id: str | None, *, report_issue: bool = True
    ) -> float | None:
        """Return a temperature entity value normalized to degrees Celsius."""
        if not entity_id:
            return None
        entity_id = str(entity_id)
        state = self.hass.states.get(entity_id)
        if state is None or state.state in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
            if report_issue:
                delete_issue(
                    self.hass, self.entry.entry_id, "invalid_temperature_unit", entity_id
                )
            return None
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        value = self._temperature_to_celsius(state.state, unit)
        if report_issue:
            if value is None:
                create_issue(
                    self.hass,
                    self.entry.entry_id,
                    "invalid_temperature_unit",
                    entity_id=entity_id,
                    placeholders={"entity": entity_id, "unit": str(unit or "-")},
                    severity=ir.IssueSeverity.WARNING,
                )
            else:
                delete_issue(
                    self.hass, self.entry.entry_id, "invalid_temperature_unit", entity_id
                )
        return value

    @staticmethod
    def _temperature_to_celsius(value: Any, unit: Any) -> float | None:
        """Convert a numeric temperature to Celsius."""
        return temperature_to_celsius(value, unit)

    @staticmethod
    def _attribute_float(state: State | None, attribute: str) -> float | None:
        return attribute_float(state, attribute)

    @staticmethod
    def _position_from_state(state: State | None) -> int | None:
        return position_from_state(state)

    @staticmethod
    def _tilt_position_from_state(state: State | None) -> int | None:
        return tilt_position_from_state(state)

    def _publish(self) -> None:
        snapshot = self._command_queue.snapshot()
        self.data["command_queue"] = snapshot
        self.data["command_queue_depth"] = int(snapshot.get("depth", 0))
        self.data["command_queue_busy"] = bool(snapshot.get("busy"))
        self.data["provider_failures"] = self._provider_failures
        self.data["provider_health"] = {
            "state": "degraded" if self._provider_failures else "ok",
            "consecutive_failures": self._provider_failures,
            "retry_attempt": self._command_retry_attempts,
        }
        self.data["pending_time_rule_open_count"] = len(
            self._pending_time_rule_opens
        )
        self.data["time_rule_conflict_count"] = len(
            self.data.get("time_rule_conflicts") or []
        )
        async_dispatcher_send(self.hass, self.signal)
