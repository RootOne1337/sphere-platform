from copy import deepcopy

import pytest

import scripts.pilot.plan_owned_image_retention as retention
from scripts.pilot.plan_owned_image_retention import plan_retention

CURRENT = "c" * 40
REPO = "sphere-review-frontend"


def image(number, tags=None, *, created=None):
    return {"Id": "sha256:" + f"{number:064x}",
            "RepoTags": tags if tags is not None else [f"{REPO}:{number:040x}"],
            "Created": created or f"2026-09-{number:02d}T01:00:00Z", "Size": 1024}


def resolve(revision):
    return revision if len(revision) == 40 else revision.ljust(40, "0")


def test_all_container_dependencies_and_rollback_versions_are_retained():
    images = [image(i) for i in range(1, 6)]
    containers = [{"Id": "running", "Image": images[0]["Id"],
                   "State": {"StartedAt": "epoch1", "Status": "running"}},
                  {"Id": "stopped", "Image": images[1]["Id"],
                   "State": {"StartedAt": "epoch2", "Status": "exited"}}]
    result = plan_retention(images, containers, resolve, CURRENT)
    assert [x["imageId"] for x in result["candidateImages"]] == [images[2]["Id"]]
    assert len(result["protectedImageIds"]) == 4
    assert result["deletionPerformed"] is False
    assert result["physicalBytesReclaimed"] is None
    assert result["requiresFreshIdentityCheckBeforeApply"]


def test_current_reviewed_image_survives_even_when_older_than_rollbacks():
    images = [image(1, [f"{REPO}:{CURRENT}"]), image(2), image(3), image(4)]
    result = plan_retention(images, [], resolve, CURRENT)
    assert [x["imageId"] for x in result["candidateImages"]] == [images[1]["Id"]]


@pytest.mark.parametrize("tags", [[], [f"{REPO}:latest"], ["sphere-foreign:" + "a" * 40],
                                 [f"{REPO}:" + "a" * 40, "other:stable"]])
def test_unknown_or_partially_owned_tags_never_become_candidates(tags):
    images = [image(1, tags), image(2), image(3), image(4)]
    result = plan_retention(images, [], resolve, CURRENT)
    assert images[0]["Id"] not in [x["imageId"] for x in result["candidateImages"]]
    assert sum(result["excludedCounts"].values()) == 1


def test_missing_source_is_excluded_and_aliases_resolve_independently():
    images = [image(1, [f"{REPO}:abcdef0", f"{REPO}:abcdef1"])]
    result = plan_retention(images, [], lambda ref: None if ref.endswith("1") else CURRENT, CURRENT)
    assert result["candidateImages"] == []
    assert result["excludedCounts"] == {"unresolved-source": 1}


@pytest.mark.parametrize("keep", [0, 1, 11])
def test_rejects_policy_that_discards_rollback_or_exceeds_limit(keep):
    with pytest.raises(ValueError):
        plan_retention([], [], resolve, CURRENT, keep)


def test_ties_are_deterministic_and_input_is_unchanged():
    images = [image(i, created="2026-09-01T01:00:00Z") for i in range(1, 5)]
    original = deepcopy(images)
    forward = plan_retention(images, [], resolve, CURRENT)
    backward = plan_retention(list(reversed(images)), [], resolve, CURRENT)
    assert forward["candidateImages"] == backward["candidateImages"]
    assert forward["protectedImageIds"] == backward["protectedImageIds"]
    assert images == original


def test_invalid_time_or_duplicate_identity_is_not_silently_accepted():
    with pytest.raises(ValueError):
        plan_retention([image(1), image(1)], [], resolve, CURRENT)
    with pytest.raises(ValueError):
        plan_retention([image(1, created="2026-09-01T01:00:00")], [], resolve, CURRENT)


@pytest.mark.parametrize("change_epoch", [False, True])
def test_cli_is_read_only_and_changed_container_epoch_discards_plan(tmp_path, monkeypatch, change_epoch):
    import json

    (tmp_path / ".local-pilot").mkdir()
    monkeypatch.setattr(retention, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["retention", "--current-commit", CURRENT])
    calls = []
    container_reads = 0
    container = {"Id": "container1", "Image": image(1)["Id"],
                 "State": {"StartedAt": "original-epoch", "Status": "running"}}

    def native(*arguments):
        nonlocal container_reads
        calls.append(arguments)
        if arguments[:2] == ("git", "rev-parse"):
            return CURRENT
        if arguments[:3] == ("docker", "image", "ls"):
            return image(1)["Id"] + "\n"
        if arguments[:3] == ("docker", "image", "inspect"):
            return json.dumps([image(1)])
        if arguments[:2] == ("docker", "ps"):
            return "container1\n"
        if arguments[:3] == ("docker", "container", "inspect"):
            container_reads += 1
            value = deepcopy(container)
            if change_epoch and container_reads == 2:
                value["State"]["StartedAt"] = "restarted-epoch"
            return json.dumps([value])
        pytest.fail(f"Unexpected native action: {arguments}")

    monkeypatch.setattr(retention, "command", native)
    if change_epoch:
        with pytest.raises(ValueError, match="baseline changed"):
            retention.main()
        assert list((tmp_path / ".local-pilot").iterdir()) == []
    else:
        retention.main()
        files = list((tmp_path / ".local-pilot").iterdir())
        assert len(files) == 1
        assert json.loads(files[0].read_text())["deletionPerformed"] is False
    assert not any("rm" in call or "prune" in call or "restart" in call for call in calls)
