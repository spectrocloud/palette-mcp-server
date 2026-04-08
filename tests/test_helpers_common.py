from helpers import (
    _normalize_tag_value,
    build_headers,
    ensure_otlp_traces_path,
    extract_cluster_profile_tags,
)


def test_ensure_otlp_traces_path_appends_default_path():
    assert (
        ensure_otlp_traces_path("http://collector:4318")
        == "http://collector:4318/v1/traces"
    )


def test_ensure_otlp_traces_path_preserves_existing_path():
    endpoint = "http://collector:4318/custom/v1/traces"
    assert ensure_otlp_traces_path(endpoint) == endpoint


def test_build_headers_includes_project_and_content_type():
    headers = build_headers(
        api_key="palette-key",
        project_id="project-uid",
        include_content_type=True,
    )
    assert headers["apiKey"] == "palette-key"
    assert headers["ProjectUid"] == "project-uid"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"


def test_normalize_tag_value_handles_dict_and_marker_values():
    value = {"env": "prod", "region": "spectro__tag", "team": ""}
    assert sorted(_normalize_tag_value(value)) == ["env:prod", "region", "team"]


def test_extract_cluster_profile_tags_prefers_metadata_tags_and_dedupes():
    profile = {
        "metadata": {
            "tags": ["env:dev", "env:dev", "owner:sre"],
            "labels": {"ignored": "because-tags-exist"},
        }
    }
    assert extract_cluster_profile_tags(profile) == ["env:dev", "owner:sre"]


def test_extract_cluster_profile_tags_falls_back_to_labels():
    profile = {"metadata": {"labels": {"env": "prod", "owner": "spectro__tag"}}}
    assert extract_cluster_profile_tags(profile) == ["env:prod", "owner"]
