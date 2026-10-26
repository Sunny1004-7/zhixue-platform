from app.models import PromptTemplate
from app.seed import seed_database


def test_question_prompt_upgrade_preserves_prior_template_and_remains_idempotent(client):
    with client.app.state.db.session_factory() as db:
        previous=db.get(PromptTemplate,'a3-question-generation-prompt-1')
        original=previous.system_template,previous.user_template,previous.template_hash
        assert previous.version=='1.0.0' and not previous.active
        latest=db.get(PromptTemplate,'a3-question-generation-prompt-2')
        assert latest.version=='1.1.0' and latest.active
        assert '第三级仍只提供求解框架' in latest.system_template
        seed_database(db,client.app.state.settings.fact_source)
        assert (previous.system_template,previous.user_template,previous.template_hash)==original
        assert not previous.active and latest.active
        tutor_previous=db.get(PromptTemplate,'a5-tutor-reply-prompt-1')
        tutor_latest=db.get(PromptTemplate,'a5-tutor-reply-prompt-2')
        assert tutor_previous.version=='1.0.0' and not tutor_previous.active
        assert tutor_latest.version=='1.1.0' and tutor_latest.active
        assert '面向学生的教学语言' in tutor_latest.system_template
