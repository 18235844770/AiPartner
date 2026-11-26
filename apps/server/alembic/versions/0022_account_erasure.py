"""Erase account-owned rows in dependency order after reauthentication."""

from alembic import op


revision = "0022_account_erasure"
down_revision = "0021_companion_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION erase_companion_account(account_id uuid) RETURNS void
        LANGUAGE plpgsql AS $$
        DECLARE
            companion_ids uuid[];
            thread_ids uuid[];
            memory_ids uuid[];
        BEGIN
            PERFORM id FROM users WHERE id = account_id AND status = 'deleting' FOR UPDATE;
            IF NOT FOUND THEN
                RETURN;
            END IF;

            SELECT ARRAY(SELECT id FROM companions WHERE owner_user_id = account_id) INTO companion_ids;
            SELECT ARRAY(SELECT id FROM conversations WHERE user_id = account_id) INTO thread_ids;
            SELECT ARRAY(SELECT id FROM memories WHERE companion_id = ANY(companion_ids)) INTO memory_ids;

            DELETE FROM model_call_logs WHERE companion_id = ANY(companion_ids) OR conversation_id = ANY(thread_ids)
                OR background_task_id IN (SELECT id FROM background_tasks WHERE companion_id = ANY(companion_ids))
                OR dialogue_decision_id IN (SELECT id FROM dialogue_decisions WHERE companion_id = ANY(companion_ids));
            DELETE FROM background_tasks WHERE companion_id = ANY(companion_ids);
            DELETE FROM audio_assets WHERE companion_id = ANY(companion_ids);
            DELETE FROM audio_tasks WHERE companion_id = ANY(companion_ids);
            DELETE FROM companion_voice_presets WHERE companion_id = ANY(companion_ids);
            DELETE FROM companion_voice_profiles WHERE companion_id = ANY(companion_ids);
            DELETE FROM state_events WHERE companion_id = ANY(companion_ids);
            DELETE FROM companion_states WHERE companion_id = ANY(companion_ids);
            DELETE FROM attention_topic_memories WHERE companion_id = ANY(companion_ids);
            DELETE FROM working_memories WHERE companion_id = ANY(companion_ids);
            DELETE FROM attention_topics WHERE companion_id = ANY(companion_ids);
            DELETE FROM memory_sources WHERE memory_id = ANY(memory_ids) OR source_memory_id = ANY(memory_ids)
                OR message_id IN (SELECT id FROM messages WHERE conversation_id = ANY(thread_ids));
            DELETE FROM memory_relations WHERE source_memory_id = ANY(memory_ids) OR target_memory_id = ANY(memory_ids);
            DELETE FROM memory_embeddings WHERE memory_version_id IN (
                SELECT id FROM memory_versions WHERE memory_id = ANY(memory_ids)
            );
            DELETE FROM memory_versions WHERE memory_id = ANY(memory_ids);
            DELETE FROM memories WHERE id = ANY(memory_ids);
            DELETE FROM persona_versions WHERE persona_profile_id IN (
                SELECT id FROM persona_profiles WHERE companion_id = ANY(companion_ids)
            );
            DELETE FROM persona_profiles WHERE companion_id = ANY(companion_ids);
            DELETE FROM dialogue_decisions WHERE companion_id = ANY(companion_ids);
            DELETE FROM messages WHERE conversation_id = ANY(thread_ids);
            DELETE FROM conversations WHERE id = ANY(thread_ids);
            DELETE FROM companions WHERE id = ANY(companion_ids);
            DELETE FROM users WHERE id = account_id;
        END;
        $$;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION erase_companion_account(uuid)")
