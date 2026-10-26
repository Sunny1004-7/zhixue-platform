from __future__ import annotations


def test_profile_catalog_keeps_display_and_provider_identity_separate(client, student_headers):
    response = client.get("/api/v1/model-profiles?task_kind=tutoring", headers=student_headers)
    assert response.status_code == 200
    profiles = response.json()
    assert {item["display_name"] for item in profiles} == {
        "GPT-5", "DeepSeek-V4.1-Flash-1017", "Qwen3-235B-A22B", "GLM-4.5",
    }
    assert all("provider_model_id" not in item for item in profiles)
    assert all(item["config_revision"] == ("deepseek-flash-2026-10-26" if item["id"] == "deepseek-flash" else "profile-catalog-2026-08-02") for item in profiles)


def test_deepseek_profile_is_explicitly_unavailable_without_runtime_authorization(
    client, student_headers, monkeypatch
):
    for name in (
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_BASE",
        "DEEPSEEK_MODEL_ID",
        "ZHIXING_MODEL_ALLOWED_DATA_REGIONS",
        "ZHIXING_MODEL_ALLOWED_RETENTION_POLICIES",
    ):
        monkeypatch.delenv(name, raising=False)

    response = client.get(
        "/api/v1/model-profiles?task_kind=a2.graph_extract",
        headers=student_headers,
    )
    assert response.status_code == 200
    deepseek = next(item for item in response.json() if item["id"] == "deepseek-flash")
    assert deepseek["available"] is False
    assert deepseek["unavailable_reason"]
    assert "provider_model_id" not in deepseek


class DeterministicTestAdapter:
    """仅供测试使用；生产包中不存在固定AI回复。"""

    def run(self, requested_profile_id: str, task_kind: str) -> dict[str, str]:
        return {
            "requested_profile_id": requested_profile_id,
            "actual_profile_id": requested_profile_id,
            "provider_model_id": "test/deterministic-adapter",
            "task_kind": task_kind,
            "status": "validated",
        }


def test_deterministic_adapter_preserves_requested_and_actual_fields():
    result = DeterministicTestAdapter().run("gpt-5", "question_generation")
    assert result["requested_profile_id"] == "gpt-5"
    assert result["actual_profile_id"] == "gpt-5"
    assert result["provider_model_id"].startswith("test/")
