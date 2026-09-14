"""SQLModel table definitions for Brein tables (PostgreSQL)."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlmodel import Field, SQLModel


class ServiceConfig(SQLModel, table=True):
    __tablename__ = "service_config"

    service_id: str = Field(primary_key=True)
    base_url: str
    api_key: str


class AppInstance(SQLModel, table=True):
    __tablename__ = "app_instances"

    id: Optional[int] = Field(default=None, primary_key=True)
    service_type: str
    label: str
    host: str = Field(default="")
    port: Optional[int] = Field(default=None)
    api_key: str = Field(default="")
    external_url: str = Field(default="")
    active: bool = Field(default=True)
    sort_order: int = Field(default=0)
    media_server_id: Optional[str] = Field(default=None)
    server_name: Optional[str] = Field(default=None)
    server_version: Optional[str] = Field(default=None)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(primary_key=True)
    username: str = Field(sa_column=Column(CITEXT, unique=True, nullable=False))
    hashed_password: str
    email: Optional[str] = Field(default=None)
    full_name: Optional[str] = Field(default=None)
    is_admin: bool = Field(default=False)
    disabled: bool = Field(default=False)
    created_at: float
    # role: 'admin' | 'viewer' | 'user' (default). is_admin is kept in sync.
    role: str = Field(default="user")
    # Emby passthrough auth — set for users imported from Emby.
    emby_instance_id: Optional[int] = Field(default=None)
    emby_username: Optional[str] = Field(default=None)
    # Jellyfin passthrough auth — set for users imported from Jellyfin.
    jellyfin_instance_id: Optional[int] = Field(default=None)
    jellyfin_username: Optional[str] = Field(default=None)
    # Login tracking metadata.
    last_login_at: Optional[float] = Field(default=None)
    last_failed_login_at: Optional[float] = Field(default=None)
    failed_login_attempts: int = Field(default=0)
    last_login_ip: Optional[str] = Field(default=None)
    last_login_user_agent: Optional[str] = Field(default=None)


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"

    id: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    token_hash: str = Field(index=True)
    expires_at: float
    created_at: float


class TokenBlacklist(SQLModel, table=True):
    __tablename__ = "token_blacklist"

    jti: str = Field(primary_key=True)
    expires_at: float = Field(index=True)


class EmbyActivityLogEntry(SQLModel, table=True):
    __tablename__ = "emby_activity_log_entries"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    entry_id: int = Field(primary_key=True)
    name: Optional[str] = Field(default=None)
    type: Optional[str] = Field(default=None)
    item_id: Optional[int] = Field(default=None)
    date: str
    user_id: Optional[int] = Field(default=None)
    overview: Optional[str] = Field(default=None)


class EmbyPlaybackSession(SQLModel, table=True):
    __tablename__ = "emby_playback_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(
        index=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    user_id: Optional[int] = Field(default=None)
    item_id: Optional[int] = Field(default=None)
    start_time: str
    end_time: str
    duration_seconds: int


class EmbyPlaybackSessionsState(SQLModel, table=True):
    __tablename__ = "emby_playback_sessions_state"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    last_entry_id: int


class EmbyItem(SQLModel, table=True):
    __tablename__ = "emby_items"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    item_id: str = Field(primary_key=True)
    type: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    server_id: Optional[str] = Field(default=None)
    series_id: Optional[str] = Field(default=None)
    season_id: Optional[str] = Field(default=None)
    parent_id: Optional[str] = Field(default=None)
    run_time_ticks: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    index_number: Optional[int] = Field(default=None)
    parent_index_number: Optional[int] = Field(default=None)
    updated_at: Optional[str] = Field(default=None)


class EmbyItemsState(SQLModel, table=True):
    __tablename__ = "emby_items_state"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    last_scan_date: Optional[str] = Field(default=None)


class EmbyUser(SQLModel, table=True):
    __tablename__ = "emby_users"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    user_id: str = Field(primary_key=True)
    name: Optional[str] = Field(default=None)
    server_id: Optional[str] = Field(default=None)
    prefix: Optional[str] = Field(default=None)
    has_password: Optional[int] = Field(default=None)
    has_configured_password: Optional[int] = Field(default=None)
    date_created: Optional[str] = Field(default=None)
    last_login_date: Optional[str] = Field(default=None)
    last_activity_date: Optional[str] = Field(default=None)
    primary_image_tag: Optional[str] = Field(default=None)
    is_administrator: Optional[int] = Field(default=None)
    is_disabled: Optional[int] = Field(default=None)
    locked_out_date: Optional[str] = Field(default=None)
    enable_all_folders: Optional[int] = Field(default=None)
    invalid_login_attempt_count: Optional[int] = Field(default=None)
    enabled_folders: Optional[str] = Field(default=None)
    is_deleted: int = Field(default=0)
    user_item_id: Optional[str] = Field(default=None)


class EmbyUserItemIdSkip(SQLModel, table=True):
    __tablename__ = "emby_user_item_id_skip"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    user_id: str = Field(primary_key=True)


class EmbyMetricsSnapshot(SQLModel, table=True):
    __tablename__ = "emby_metrics_snapshot"

    stat_date: str = Field(primary_key=True)
    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE", index=True
    )
    total_plays: int = Field(default=0)
    total_watch_time_seconds: int = Field(default=0)
    total_movies: int = Field(default=0)
    total_episodes: int = Field(default=0)
    total_live_tv: int = Field(default=0)


class EmbyMetricsSnapshotUser(SQLModel, table=True):
    __tablename__ = "emby_metrics_snapshot_user"

    stat_date: str = Field(primary_key=True)
    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE", index=True
    )
    user_id: str = Field(primary_key=True)
    user_name: Optional[str] = Field(default=None)
    plays: int = Field(default=0)
    watch_time_seconds: int = Field(default=0)


class UserPreference(SQLModel, table=True):
    __tablename__ = "user_preferences"

    user_id: str = Field(primary_key=True)
    key: str = Field(primary_key=True)
    value: str  # JSON-encoded


class EmbyMetricsSnapshotItem(SQLModel, table=True):
    __tablename__ = "emby_metrics_snapshot_item"

    stat_date: str = Field(primary_key=True)
    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE", index=True
    )
    item_id: str = Field(primary_key=True)
    item_name: Optional[str] = Field(default=None)
    item_type: Optional[str] = Field(default=None)
    series_id: Optional[str] = Field(default=None)
    series_name: Optional[str] = Field(default=None)
    display_label: Optional[str] = Field(default=None)
    plays: int = Field(default=0)


# ---------------------------------------------------------------------------
# Jellyfin tables (mirror of Emby tables, separate storage)
# ---------------------------------------------------------------------------


class JellyfinActivityLogEntry(SQLModel, table=True):
    __tablename__ = "jellyfin_activity_log_entries"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    entry_id: int = Field(primary_key=True)
    name: Optional[str] = Field(default=None)
    type: Optional[str] = Field(default=None)
    item_id: Optional[str] = Field(default=None)
    date: str
    user_id: Optional[str] = Field(default=None)
    overview: Optional[str] = Field(default=None)


class JellyfinPlaybackSession(SQLModel, table=True):
    __tablename__ = "jellyfin_playback_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(
        index=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    user_id: Optional[str] = Field(default=None)
    item_id: Optional[str] = Field(default=None)
    start_time: str
    end_time: str
    duration_seconds: int


class JellyfinPlaybackSessionsState(SQLModel, table=True):
    __tablename__ = "jellyfin_playback_sessions_state"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    last_entry_id: int


class JellyfinItem(SQLModel, table=True):
    __tablename__ = "jellyfin_items"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    item_id: str = Field(primary_key=True)
    type: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    server_id: Optional[str] = Field(default=None)
    series_id: Optional[str] = Field(default=None)
    season_id: Optional[str] = Field(default=None)
    parent_id: Optional[str] = Field(default=None)
    run_time_ticks: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    index_number: Optional[int] = Field(default=None)
    parent_index_number: Optional[int] = Field(default=None)
    updated_at: Optional[str] = Field(default=None)


class JellyfinItemsState(SQLModel, table=True):
    __tablename__ = "jellyfin_items_state"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    last_scan_date: Optional[str] = Field(default=None)


class PlexItem(SQLModel, table=True):
    __tablename__ = "plex_items"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    item_id: str = Field(primary_key=True)
    type: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    server_id: Optional[str] = Field(default=None)
    series_id: Optional[str] = Field(default=None)
    season_id: Optional[str] = Field(default=None)
    parent_id: Optional[str] = Field(default=None)
    run_time_ticks: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    index_number: Optional[int] = Field(default=None)
    parent_index_number: Optional[int] = Field(default=None)
    updated_at: Optional[str] = Field(default=None)
    library_section_id: Optional[str] = Field(default=None)
    guid: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))


class PlexItemsState(SQLModel, table=True):
    __tablename__ = "plex_items_state"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    last_scan_date: Optional[str] = Field(default=None)


class PlexUser(SQLModel, table=True):
    __tablename__ = "plex_users"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    user_id: int = Field(primary_key=True)
    uuid: Optional[str] = Field(default=None)
    title: Optional[str] = Field(default=None)
    username: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    thumb: Optional[str] = Field(default=None)
    home: int = Field(default=0)
    restricted: int = Field(default=0)
    admin: int = Field(default=0)
    is_deleted: int = Field(default=0)


class PlexWsEvent(SQLModel, table=True):
    __tablename__ = "plex_ws_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(
        index=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    received_at: float = Field(index=True)
    event_type: Optional[str] = Field(default=None, index=True)
    raw_payload: str = Field(default="")


class PlexPlaybackSessionActive(SQLModel, table=True):
    __tablename__ = "plex_playback_sessions_active"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    plex_session_key: str = Field(primary_key=True)
    account_id: Optional[int] = Field(default=None)
    account_title: Optional[str] = Field(default=None, max_length=512)
    rating_key: Optional[str] = Field(default=None)
    item_type: Optional[str] = Field(default=None)
    title: Optional[str] = Field(default=None)
    grandparent_title: Optional[str] = Field(default=None)
    parent_title: Optional[str] = Field(default=None)
    view_offset_ms: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False, server_default="0")
    )
    duration_ms: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    started_at_wall: float = 0.0
    last_seen_at_wall: float = 0.0


class PlexPlaybackSession(SQLModel, table=True):
    __tablename__ = "plex_playback_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(
        index=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    account_id: Optional[int] = Field(default=None, index=True)
    account_title: Optional[str] = Field(default=None, max_length=512)
    rating_key: Optional[str] = Field(default=None)
    item_type: Optional[str] = Field(default=None)
    title: Optional[str] = Field(default=None)
    grandparent_title: Optional[str] = Field(default=None)
    parent_title: Optional[str] = Field(default=None)
    plex_session_key: str = Field(default="", index=True)
    start_time: str = Field(default="")
    end_time: str = Field(default="")
    # server_default as well as the Python default: a Field's own default
    # never reaches an explicit sa_column, and db.py's ADD COLUMN repair reads
    # the Column — so without it this could not be added to an existing table.
    watched_seconds: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False, server_default="0")
    )


class PlexMetricsSnapshot(SQLModel, table=True):
    __tablename__ = "plex_metrics_snapshot"

    stat_date: str = Field(primary_key=True)
    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE", index=True
    )
    total_plays: int = Field(default=0)
    total_watch_time_seconds: int = Field(default=0)
    total_movies: int = Field(default=0)
    total_episodes: int = Field(default=0)
    total_live_tv: int = Field(default=0)


class PlexMetricsSnapshotUser(SQLModel, table=True):
    __tablename__ = "plex_metrics_snapshot_user"

    stat_date: str = Field(primary_key=True)
    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE", index=True
    )
    user_id: str = Field(primary_key=True)
    user_name: Optional[str] = Field(default=None)
    plays: int = Field(default=0)
    watch_time_seconds: int = Field(default=0)


class PlexMetricsSnapshotItem(SQLModel, table=True):
    __tablename__ = "plex_metrics_snapshot_item"

    stat_date: str = Field(primary_key=True)
    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE", index=True
    )
    item_id: str = Field(primary_key=True)
    item_name: Optional[str] = Field(default=None)
    item_type: Optional[str] = Field(default=None)
    series_id: Optional[str] = Field(default=None)
    series_name: Optional[str] = Field(default=None)
    display_label: Optional[str] = Field(default=None)
    plays: int = Field(default=0)


class JellyfinUser(SQLModel, table=True):
    __tablename__ = "jellyfin_users"

    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE"
    )
    user_id: str = Field(primary_key=True)
    name: Optional[str] = Field(default=None)
    server_id: Optional[str] = Field(default=None)
    prefix: Optional[str] = Field(default=None)
    has_password: Optional[int] = Field(default=None)
    has_configured_password: Optional[int] = Field(default=None)
    date_created: Optional[str] = Field(default=None)
    last_login_date: Optional[str] = Field(default=None)
    last_activity_date: Optional[str] = Field(default=None)
    primary_image_tag: Optional[str] = Field(default=None)
    is_administrator: Optional[int] = Field(default=None)
    is_disabled: Optional[int] = Field(default=None)
    locked_out_date: Optional[str] = Field(default=None)
    enable_all_folders: Optional[int] = Field(default=None)
    invalid_login_attempt_count: Optional[int] = Field(default=None)
    enabled_folders: Optional[str] = Field(default=None)
    is_deleted: int = Field(default=0)


class JellyfinMetricsSnapshot(SQLModel, table=True):
    __tablename__ = "jellyfin_metrics_snapshot"

    stat_date: str = Field(primary_key=True)
    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE", index=True
    )
    total_plays: int = Field(default=0)
    total_watch_time_seconds: int = Field(default=0)
    total_movies: int = Field(default=0)
    total_episodes: int = Field(default=0)
    total_live_tv: int = Field(default=0)


class JellyfinMetricsSnapshotUser(SQLModel, table=True):
    __tablename__ = "jellyfin_metrics_snapshot_user"

    stat_date: str = Field(primary_key=True)
    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE", index=True
    )
    user_id: str = Field(primary_key=True)
    user_name: Optional[str] = Field(default=None)
    plays: int = Field(default=0)
    watch_time_seconds: int = Field(default=0)


class SystemSetting(SQLModel, table=True):
    __tablename__ = "system_settings"

    key: str = Field(primary_key=True)
    value: str


class JellyfinMetricsSnapshotItem(SQLModel, table=True):
    __tablename__ = "jellyfin_metrics_snapshot_item"

    stat_date: str = Field(primary_key=True)
    instance_id: int = Field(
        primary_key=True, foreign_key="app_instances.id", ondelete="CASCADE", index=True
    )
    item_id: str = Field(primary_key=True)
    item_name: Optional[str] = Field(default=None)
    item_type: Optional[str] = Field(default=None)
    series_id: Optional[str] = Field(default=None)
    series_name: Optional[str] = Field(default=None)
    display_label: Optional[str] = Field(default=None)
    plays: int = Field(default=0)


class SabnzbdServerStatsSnapshot(SQLModel, table=True):
    __tablename__ = "sabnzbd_server_stats_snapshots"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(
        foreign_key="app_instances.id", ondelete="CASCADE", index=True
    )
    collected_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    payload: dict[str, Any] = Field(
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    )
    bytes_today: Optional[int] = Field(default=None, sa_column=Column(BigInteger()))
    bytes_week: Optional[int] = Field(default=None, sa_column=Column(BigInteger()))
    bytes_month: Optional[int] = Field(default=None, sa_column=Column(BigInteger()))
    bytes_total: Optional[int] = Field(default=None, sa_column=Column(BigInteger()))


class ScheduledTask(SQLModel, table=True):
    __tablename__ = "scheduled_tasks"
    __table_args__ = (
        UniqueConstraint(
            "key",
            "instance_id",
            name="uq_scheduled_tasks_key_instance",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_scheduled_tasks_enabled_last_run", "enabled", "last_run_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True)
    name: str
    instance_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("app_instances.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    interval_seconds: int = Field(default=3600)
    enabled: bool = Field(default=True)
    category: str = Field(default="sync")
    config_json: str = Field(
        default="{}", sa_column=Column(Text, nullable=False, server_default="{}")
    )
    last_run_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_status: Optional[str] = Field(default=None)
    last_duration_ms: Optional[int] = Field(default=None)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )


class ScheduledTaskRun(SQLModel, table=True):
    __tablename__ = "scheduled_task_runs"
    __table_args__ = (
        Index("ix_scheduled_task_runs_task_started", "task_id", "started_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("scheduled_tasks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    started_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    finished_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    status: str = Field(default="running")
    error_message: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    duration_ms: Optional[int] = Field(default=None)
