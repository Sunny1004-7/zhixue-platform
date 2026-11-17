from sqlalchemy import select

from app.config import Settings
from app.domains.model_gateway.catalog_seed import seed_model_catalog
from app.domains.model_gateway.profile_catalog import resolve_profile
from app.models import ModelProfile, ModelProfileRevision


def test_two_models_resolve_independent_ids_and_legacy_flash_variable(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    monkeypatch.setenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
    monkeypatch.setenv("DEEPSEEK_MODEL_ID", "legacy-flash")
    monkeypatch.setenv("DEEPSEEK_PRO_MODEL_ID", "deepseek-v4-pro")
    monkeypatch.setenv("ZHIXING_MODEL_ALLOWED_DATA_REGIONS", "deployment_configured")
    monkeypatch.setenv("ZHIXING_MODEL_ALLOWED_RETENTION_POLICIES", "provider_account_policy")
    with client.app.state.db.session_factory() as db:
        flash = db.get(ModelProfile, "deepseek-flash")
        pro = db.get(ModelProfile, "deepseek-pro")
        assert resolve_profile(db, flash, "a5.tutor_reply").provider_model_id == "legacy-flash"
        assert resolve_profile(db, pro, "a5.tutor_reply").provider_model_id == "deepseek-v4-pro"
        monkeypatch.setenv("DEEPSEEK_FLASH_MODEL_ID", "deepseek-flash")
        assert resolve_profile(db, flash, "a5.tutor_reply").provider_model_id == "deepseek-flash"


def test_upgrade_retires_old_revision_and_preserves_legacy_profile(client):
    with client.app.state.db.session_factory() as db:
        flash = db.get(ModelProfile, "deepseek-flash")
        current = db.scalar(select(ModelProfileRevision).where(ModelProfileRevision.profile_id == flash.id))
        current.model_id_ref = "DEEPSEEK_MODEL_ID"
        db.add(ModelProfile(id="gpt-5", display_name="GPT-5", enabled=True,
                            task_kinds=["a5.tutor_reply"], config_revision="historic"))
        db.flush()
        seed_model_catalog(db)
        seed_model_catalog(db)
        db.flush()
        revisions = list(db.scalars(select(ModelProfileRevision).where(ModelProfileRevision.profile_id == flash.id)))
        assert len(revisions) == 2
        assert current.status == "retired"
        assert [r.model_id_ref for r in revisions if r.status == "active"] == ["DEEPSEEK_FLASH_MODEL_ID"]
        assert not db.get(ModelProfile, "gpt-5").enabled


def test_dotenv_keeps_explicit_database_and_uses_backend_relative_paths(tmp_path, monkeypatch):
    envfile = tmp_path / "backend.env"
    envfile.write_text("DEEPSEEK_FLASH_MODEL_ID=from-file\nZHIXING_DATABASE_URL=sqlite:///wrong.db\n", encoding="utf-8")
    monkeypatch.setenv("ZHIXING_ENV_FILE", str(envfile))
    monkeypatch.setenv("ZHIXING_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("DEEPSEEK_FLASH_MODEL_ID", "explicit-model")
    settings = Settings.from_env()
    assert settings.database_url == "sqlite:///:memory:"
    import os
    assert os.environ["DEEPSEEK_FLASH_MODEL_ID"] == "explicit-model"
