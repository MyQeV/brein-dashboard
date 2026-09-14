# Integration clients for external APIs (Sonarr, Radarr, Plex, etc.)
# Re-export API subpackage so "from brein.integrations import emby" still works.
from brein.integrations.api import (
    base as base,
    emby as emby,
    jellyfin as jellyfin,
    plex as plex,
    radarr as radarr,
    sonarr as sonarr,
)
