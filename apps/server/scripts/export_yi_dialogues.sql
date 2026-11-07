SELECT coalesce(json_agg(c ORDER BY c.created_at), '[]'::json)
FROM (
  SELECT
    comp.id,
    comp.owner_user_id,
    u.display_name AS owner_name,
    comp.name,
    comp.created_at,
    pv.mbti_type,
    (
      SELECT coalesce(json_agg(conv ORDER BY conv.created_at), '[]'::json)
      FROM (
        SELECT
          cv.id,
          cv.title,
          cv.status,
          cv.created_at,
          (
            SELECT coalesce(json_agg(msg ORDER BY msg.sequence_number), '[]'::json)
            FROM (
              SELECT m.id, m.sequence_number, m.sender_type, m.content, m.status, m.created_at
              FROM messages m
              WHERE m.conversation_id = cv.id
            ) msg
          ) AS messages,
          (
            SELECT coalesce(json_agg(dec ORDER BY dec.created_at), '[]'::json)
            FROM (
              SELECT
                d.id,
                d.trigger_message_id,
                d.result_message_id,
                d.trigger_type,
                d.primary_action,
                d.secondary_actions,
                d.motivation,
                d.topic,
                d.model_proposal,
                d.validation_result,
                d.confidence,
                d.reasoning_summary,
                d.status,
                d.created_at,
                d.completed_at
              FROM dialogue_decisions d
              WHERE d.conversation_id = cv.id
            ) dec
          ) AS decisions
        FROM conversations cv
        WHERE cv.companion_id = comp.id
      ) conv
    ) AS conversations
  FROM companions comp
  JOIN users u ON u.id = comp.owner_user_id
  LEFT JOIN persona_profiles pp ON pp.companion_id = comp.id
  LEFT JOIN persona_versions pv ON pv.id = pp.current_version_id
  WHERE comp.name = '艺'
) c;
