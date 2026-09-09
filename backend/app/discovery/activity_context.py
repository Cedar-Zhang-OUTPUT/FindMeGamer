"""Freeze current promotion intent alongside, never inside, source facts."""

from copy import deepcopy


def activity_context(activity):
    snapshot = deepcopy(activity.source_snapshot)
    if activity.campaign_brief:
        snapshot["campaign_brief"] = activity.campaign_brief
        snapshot["campaign_brief_revision"] = activity.revision
    return snapshot
