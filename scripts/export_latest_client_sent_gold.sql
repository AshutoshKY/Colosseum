-- Query: Export latest 10 client-sent claims with diverse page counts and page types from superclaims-ai (v2).
--
-- Run with:
--   psql "$SUPERCLAIMS_DATABASE_URL" -tA -f scripts/export_latest_client_sent_gold.sql > latest_10_gold.jsonl
--
-- Criteria:
--   1. Filter for claims sent to client (client_sent_at IS NOT NULL or status = 'CLIENT_SENT')
--   2. Pick 10 claims with DISTINCT page counts (c.pages: e.g. 1, 2, 3, 4, 5, 6, 7, 8, 10, 15+ pages)
--   3. Prioritize rich page type variety (prescriptions, itemized bills, bank details, claim forms, IDs)
--   4. Include all 11 detail tasks (patient summary, cheque bank, bills, categorization, nme, audit, etc.)

WITH client_sent_candidates AS (
  SELECT
    c.id,
    c.claim_id,
    c.claim_type,
    c.pages,
    c.segments,
    c.doc_details,
    c.client_reference_id,
    c.claim_reference_id,
    c.user_id,
    c.dependent_id,
    c.insurer_name,
    c.company_name,
    rs.client_sent_at,
    rs.submitted_at,
    rs.updated_at,
    -- Rank by latest sent date within each distinct page count
    ROW_NUMBER() OVER (
      PARTITION BY c.pages
      ORDER BY
        COALESCE(rs.client_sent_at, rs.submitted_at, rs.updated_at) DESC,
        -- Prefer claims with more distinct document segments
        CASE WHEN c.segments IS NOT NULL AND jsonb_typeof(c.segments::jsonb) = 'array'
             THEN jsonb_array_length(c.segments::jsonb)
             ELSE 0
        END DESC
    ) AS rank_in_page_bucket
  FROM claims c
  JOIN review_sessions rs ON rs.claim_id = c.id
  WHERE (
    rs.client_sent_at IS NOT NULL
    OR rs.status IN ('CLIENT_SENT', 'SUBMITTED')
    OR rs.submitted_at IS NOT NULL
  )
  AND c.pages > 0
  AND c.segments IS NOT NULL
),
selected_10_claims AS (
  SELECT *
  FROM client_sent_candidates
  WHERE rank_in_page_bucket = 1
  ORDER BY
    COALESCE(client_sent_at, submitted_at, updated_at) DESC,
    pages ASC
  LIMIT 10
)
SELECT json_build_object(
  'source',              'superclaims-ai:v2',
  'stem',                m.claim_id,
  'claim_id',            m.claim_id,
  'claim_type',          m.claim_type,
  'pages',               m.pages,
  'client_reference_id', m.client_reference_id,
  'claim_reference_id',  m.claim_reference_id,
  'user_id',             m.user_id,
  'dependent_id',        m.dependent_id,
  'insurer_name',        m.insurer_name,
  'company_name',        m.company_name,
  'client_sent_at',      m.client_sent_at,
  'segments',            m.segments,
  'doc_details',         m.doc_details,
  'policy_extraction',   COALESCE(
                           m.doc_details->'policy_extraction',
                           m.doc_details->'policy_details',
                           m.doc_details->'policy'
                         ),
  'extracted',  (SELECT json_object_agg(ed.document_type, ed.json_data)
                 FROM extracted_data ed
                 WHERE ed.claim_id = m.id),
  'review',     (SELECT json_agg(json_build_object(
                          'status',           rs.status,
                          'submitted_at',     rs.submitted_at,
                          'updated_at',       rs.updated_at,
                          'client_sent_at',   rs.client_sent_at,
                          'original_payload', rs.original_payload,
                          'edited_payload',   rs.edited_payload)
                        ORDER BY rs.updated_at DESC)
                 FROM review_sessions rs
                 WHERE rs.claim_id = m.id),
  'patches',    (SELECT json_agg(json_build_object(
                          'patch_type',  rsp.patch_type,
                          'patch_data',  rsp.patch_data,
                          'is_applied',  rsp.is_applied,
                          'description', rsp.description)
                        ORDER BY rsp.created_at)
                 FROM review_sessions rs
                 JOIN review_session_patches rsp ON rsp.session_id = rs.id
                 WHERE rs.claim_id = m.id)
)
FROM selected_10_claims m;
