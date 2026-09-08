"""Real API/Celery/PG Analyze smoke, synthetic upstreams only; owned instance."""

from collections import Counter
import json
from pathlib import Path
import secrets
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "match_frontend"))
from manage import command, load_owned, private_write, request
from smoke import poll, require

PIN = "5706ad76f924991b80ee2a7fb6806528366be5ce"


def events(directory):
    path = directory / "state/events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def counts(directory, offset):
    return Counter(row["endpoint"] for row in events(directory)[offset:])


def require_youtube_counts(actual, *, brief_calls=1):
    for label in ("youtube_channel", "youtube_playlist", "youtube_videos", "creator_map_00", "creator_map_01", "creator_visual", "creator_content", "creator_presentation", "creator_performance", "creator_commercial"):
        require(actual.get(label, 0) == 1, "Unexpected Analyze count: " + label)
    require(actual.get("creator_brief", 0) == brief_calls, "Brief retry count differs")
    require(actual.get("asset_download", 0) == 2, "Real thumbnail downloads missing/repeated")


def control(directory, *, stage="none", mode="none"):
    require(stage in {"none", "creator_brief"} and mode in {"none", "once", "always"}, "Unsupported control")
    private_write(directory / "state/analyze-control.json", json.dumps({"stage": stage, "mode": mode, "token": secrets.token_hex(8)}), replace=True)


def run(directory):
    config = load_owned(directory)
    require(config["backend_revision"] == PIN, "Analyze requires its own accepted pin")
    migration = command(directory, "exec", "-T", "postgres", "psql", "-U", "match_fixture", "-d", "match_frontend", "-Atc", "SELECT version_num FROM alembic_version")
    require(migration == "20260908_0019", "Wrong actual migration")
    report = {"backend_revision": PIN, "migration": migration, "checks": []}
    control(directory)

    def api(method, path, body=None):
        return request(config, method, path, body)

    def analyze(kind, url):
        job = api("POST", "/api/v1/jobs/analysis", {"target_type": kind, "url": url, "mode": "reanalyze"})
        return job["id"]

    def terminal(job_id, *, success=True):
        result = poll(config, f"/api/v1/jobs/{job_id}", lambda row: row["status"] in {"succeeded", "failed"}, seconds=150)
        require(result["status"] == ("succeeded" if success else "failed"), "Analyze terminal mismatch: " + str(result.get("error_code")))
        return result

    try:
        offset = len(events(directory))
        game = api("POST", "/api/v2/library/games", {"name": "Human Station", "reference_works": [{"name": "Human reference", "similarities": ["Co-op"], "reason": "Synthetic manual reference"}]})
        game_id = game["id"]
        imported = api("POST", "/api/v2/library/games/steam-import", {"url": "https://store.steampowered.com/app/900000001", "game_id": game_id, "expected_revision": game["revision"]})
        require(imported["id"] == game_id and counts(directory, offset) == {"steam": 1}, "Source-only import had extra calls or changed UUID")
        edited = api("PATCH", f"/api/v2/library/games/{game_id}", {"expected_revision": imported["revision"], "description": "Human description retained"})
        game_job = analyze("game", imported["source_identity"]["canonical_url"])
        require(terminal(game_job)["profile_id"] == game_id, "Game UUID changed")
        game_final = api("GET", f"/api/v2/library/games/{game_id}")
        require(game_final["description"] == "Human description retained" and game_final["reference_works"] == edited["reference_works"], "Game manual fields lost")
        require(counts(directory, offset) == {"steam": 2, "game_extraction": 1, "game_visual": 1, "game_synthesis": 1, "asset_download": 1}, "Game stage/download counts differ")
        report["checks"].append("steam_import_edit_analyze_same_uuid")

        creator = api("POST", "/api/v2/library/creators", {"platform": "youtube", "profile_url": "https://www.youtube.com/@analyzefixture", "name": "Human YouTube name"})
        creator_id = creator["id"]
        bound = api("POST", f"/api/v2/library/creators/{creator_id}/youtube-binding", {"url": "https://www.youtube.com/@analyzefixture", "expected_revision": creator["revision"]})
        require(bound["id"] == creator_id and bound["analysis_available"], "YT first bind failed")
        offset = len(events(directory))
        yt_job = analyze("creator", bound["source_identity"]["canonical_url"])
        require(terminal(yt_job)["profile_id"] == creator_id, "YT UUID changed")
        require_youtube_counts(counts(directory, offset))
        yt = api("GET", f"/api/v2/library/creators/{creator_id}")
        require(yt["name"] == "Human YouTube name" and yt["brief"], "YT manual name/brief missing")
        works = api("GET", f"/api/v2/library/creators/{creator_id}/works")
        require(works["total"] == 11, "YT source works missing")
        require(all(row["content_type"] == "unverified" for row in works["items"]), "False viewing/content verification")
        report["checks"].append("youtube_first_bind_eleven_videos_two_maps_real_visual_brief")

        creator_x = api("POST", "/api/v2/library/creators", {"platform": "x", "account_id": "900000001", "name": "Human X name"})
        offset = len(events(directory))
        x_job = analyze("creator", creator_x["source_identity"]["canonical_url"])
        require(terminal(x_job)["profile_id"] == creator_x["id"], "X UUID changed")
        x_final = api("GET", f"/api/v2/library/creators/{creator_x['id']}")
        require(x_final["name"] == "Human X name" and x_final["analysis"]["content_summary"]["status"] == "available", "X analysis missing")
        require(counts(directory, offset) == {"x_user": 1, "x_posts": 1, "x_map_00": 1, "x_map_01": 1, "x_map_02": 1, "x_final": 1}, "X real map/reduction counts differ")
        report["checks"].append("x_twenty_one_posts_three_maps_same_uuid")

        control(directory, stage="creator_brief", mode="always")
        failed_job = analyze("creator", bound["source_identity"]["canonical_url"])
        failed = terminal(failed_job, success=False)
        require(failed["retryable"], "Core failure not retryable")
        after = api("GET", f"/api/v2/library/creators/{creator_id}")
        require(after == yt, "Failure overwrote existing Creator")
        require(api("GET", f"/api/v2/library/creators/{creator_id}/works") == works, "Failure overwrote works")
        control(directory)
        retry = api("POST", f"/api/v1/jobs/analysis/{failed_job}/retry", {})
        require(retry["id"] != failed_job and terminal(retry["id"])["profile_id"] == creator_id, "Explicit retry failed")
        report["checks"].append("core_failure_preserves_profile_works_explicit_retry")

        offset = len(events(directory))
        control(directory, stage="creator_brief", mode="once")
        checkpoint_job = analyze("creator", bound["source_identity"]["canonical_url"])
        require(terminal(checkpoint_job)["profile_id"] == creator_id, "Checkpoint recovery failed")
        require_youtube_counts(counts(directory, offset), brief_calls=2)
        brief_events = [e["status"] for e in events(directory)[offset:] if e["endpoint"] == "creator_brief"]
        require(brief_events == [503, 200], "One actual transient brief failure not observed")
        report["checks"].append("same_job_retry_reuses_all_successful_checkpoints")
        report.update(game_id=game_id, youtube_id=creator_id, x_id=creator_x["id"], jobs=[game_job, yt_job, x_job, failed_job, retry["id"], checkpoint_job])
        private_write(directory / "analyze-report.json", json.dumps(report, indent=2), replace=True)
        return report
    finally:
        control(directory)


if __name__ == "__main__":
    print(json.dumps(run(Path(sys.argv[1])), indent=2))
