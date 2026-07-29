from typing import List

from pydantic import BaseModel, field_validator


class PluginManifest(BaseModel):
    name: str
    version: str = "0.0.0"
    thumb: str = None
    tags: List[str] = []
    description: str = (
        "Description not found for this plugin."
        "Please create a plugin.json manifest"
        " in the plugin folder."
    )
    author_name: str = "Unknown"
    author_url: str = "Unknown"
    plugin_url: str = "Unknown"
    min_cat_version: str = "Unknown"
    max_cat_version: str = ""

    # Local-only annotations attached when listing installed plugins alongside
    # registry results (e.g. {"active": bool, "upgrade": version|None}). Not part
    # of the plugin's own metadata; populated by the /registry route.
    local_info: dict = {}

    @field_validator("tags", mode="before")
    def split_comma_string(cls, v):
        """Accept a list, or the comma-separated string the registry may send.

        Manifests declare `"tags": ["a", "b"]`. The remote plugin registry is a
        separate API that still returns `"a, b"`, so parse both rather than
        rejecting plugins we did not write.
        """
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        return v
