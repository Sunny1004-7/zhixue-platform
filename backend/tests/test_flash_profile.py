from sqlalchemy import select, func
from app.models import ModelProfile,ModelProfileRevision,ModelRun,User
from app.seed import seed_database

def test_existing_catalog_preserves_legacy_runs_and_adds_flash_idempotently(client):
    with client.app.state.db.session_factory() as db:
        user=db.scalar(select(User).where(User.role=='teacher'))
        db.add(ModelProfile(id='deepseek-v3',display_name='DeepSeek-V3',enabled=True,task_kinds=['a5.tutor_reply'],config_revision='profile-catalog-2026-08-02'))
        db.flush()
        db.add(ModelProfileRevision(id='deepseek-v3:rev:1',profile_id='deepseek-v3',revision_no=1,provider_kind='deepseek',credential_ref='DEEPSEEK_API_KEY',endpoint_ref='DEEPSEEK_API_BASE',model_id_ref='DEEPSEEK_MODEL_ID',capabilities_json=['chat'],data_region='deployment_configured',retention_policy='provider_account_policy',status='active'))
        db.add(ModelRun(id='historic-model-run',actor_id=user.id,course_id='machine-learning',task_kind='a5.tutor_reply',requested_profile_id='deepseek-v3',actual_profile_id='deepseek-v3',provider_model_id='historic-provider-model',task_policy_version='1.0.0',status='validated',usage_json={'input_tokens':12},attempt_count=1))
        db.commit()
        for _ in range(2):seed_database(db,client.app.state.settings.fact_source)
        legacy=db.get(ModelProfile,'deepseek-v3');old=db.get(ModelRun,'historic-model-run')
        assert not legacy.enabled and legacy.display_name=='DeepSeek-V3'
        assert old.actual_profile_id=='deepseek-v3' and old.provider_model_id=='historic-provider-model'
        assert old.usage_json=={'input_tokens':12}
        assert db.scalar(select(func.count()).select_from(ModelProfileRevision).where(ModelProfileRevision.profile_id=='deepseek-flash'))==1
        assert db.get(ModelProfileRevision,'deepseek-v3:rev:1').revision_no==1

def test_flash_availability_requires_runtime_and_policy_authorization(client,student_headers,monkeypatch):
    for name,value in [('DEEPSEEK_API_KEY','test-only-key'),('DEEPSEEK_API_BASE','https://api.deepseek.com'),('DEEPSEEK_MODEL_ID','deepseek-flash')]:monkeypatch.setenv(name,value)
    for name in ['ZHIXING_MODEL_ALLOWED_DATA_REGIONS','ZHIXING_MODEL_ALLOWED_RETENTION_POLICIES']:monkeypatch.delenv(name,raising=False)
    def profile(task):return next(x for x in client.get('/api/v1/model-profiles',params={'task_kind':task},headers=student_headers).json() if x['id']=='deepseek-flash')
    assert not profile('a2.graph_extract')['available']
    monkeypatch.setenv('ZHIXING_MODEL_ALLOWED_DATA_REGIONS','deployment_configured')
    monkeypatch.setenv('ZHIXING_MODEL_ALLOWED_RETENTION_POLICIES','provider_account_policy')
    for task in ['a2.graph_extract','a2.graph_semantic_review','a3.question_generation','a5.tutor_reply','a5.experience_generation']:
        p=profile(task);assert p['available'] and p['display_name']=='DeepSeek-V4.1-Flash-1017'
        assert p['config_revision']=='deepseek-flash-2026-10-26'
