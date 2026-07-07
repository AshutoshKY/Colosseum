-- Colosseum ground-truth export — run against the HEALTHPAY-AI database.
--
--   psql "$HEALTHPAY_DATABASE_URL" -tA -f scripts/export_gold_healthpay.sql \
--     > healthpay_gold.jsonl
--
-- One JSON object per line per matched claim. Covers the NON-numeric test-docs stems
-- (numeric ones are FHPL claims — use export_gold_healthpay_fhpl.sql against the
-- test-fhpl database instead). Matches against claim_id / client_reference_id /
-- claim_reference_id / claim_request_id / original_filename.
--
-- What each field is:
--   policy_extraction -> gold for the `policy_extraction` task (documents.policy_extraction)
--   segments          -> gold for `segregation` (document_segments rows: type + page_range)
--   extracted         -> per-task outputs from raw_extracted_data as an ARRAY (the table has
--                        no uniqueness on document_type): pharmacy_bills, nme_analysis,
--                        audit_analysis, patient_summary, ... newest first
--   review            -> review_sessions: original_payload (model output) vs edited_payload
--                        (HUMAN-CORRECTED final = the real gold), newest first, with status.

WITH refs(stem) AS (
  VALUES
    ('E9TNRZBK'),    ('REQ65CYP9E0'), ('REQ7FSWENTC'), ('REQ9LQ8EMUG'),
    ('REQB3A0ZPJV'), ('REQC183P024'), ('REQG9M0IPNB'), ('REQGCHOM85Q'),
    ('REQN4LFJ5QW'), ('REQRM38KJOF'), ('REQSG1CBFKW'), ('REQTWKX8N5C'),
    ('REQVS8XQ3FA'), ('REQW3D6S728'), ('REQWJ74XVTG'), ('REQXFCYR1DT'),
    ('T14SBYEU'),    ('XCAS2J1V')
),
matched AS (
  SELECT r.stem, d.id, d.claim_id, d.claim_type, d.original_filename, d.policy_extraction
  FROM refs r
  JOIN documents d
    ON d.claim_id            ILIKE r.stem || '%'
    OR d.client_reference_id ILIKE r.stem || '%'
    OR d.claim_reference_id  ILIKE r.stem || '%'
    OR d.claim_request_id    ILIKE r.stem || '%'
    OR d.original_filename   ILIKE r.stem || '%'
)
SELECT json_build_object(
  'source',            'healthpay-ai',
  'stem',              m.stem,
  'claim_id',          m.claim_id,
  'claim_type',        m.claim_type,
  'original_filename', m.original_filename,
  'policy_extraction', m.policy_extraction,
  'segments',   (SELECT json_agg(json_build_object(
                          'segment_type', s.segment_type,
                          'page_range',   s.page_range)
                        ORDER BY s.created_at)
                 FROM document_segments s
                 WHERE s.parent_doc_id = m.id),
  'extracted',  (SELECT json_agg(json_build_object(
                          'document_type', ed.document_type,
                          'json_data',     ed.json_data,
                          'updated_at',    ed.updated_at)
                        ORDER BY ed.updated_at DESC)
                 FROM raw_extracted_data ed
                 WHERE ed.claim_id = m.claim_id),
  'review',     (SELECT json_agg(json_build_object(
                          'status',           rs.status,
                          'submitted_at',     rs.submitted_at,
                          'original_payload', rs.original_payload,
                          'edited_payload',   rs.edited_payload)
                        ORDER BY rs.updated_at DESC)
                 FROM review_sessions rs
                 WHERE rs.claim_id = m.claim_id)
)
FROM matched m;

-- Sanity check for unmatched stems:
--   SELECT stem FROM (VALUES ('E9TNRZBK'),('REQ65CYP9E0')) v(stem)
--   WHERE NOT EXISTS (SELECT 1 FROM documents d WHERE d.claim_id ILIKE stem || '%'
--     OR d.client_reference_id ILIKE stem || '%' OR d.claim_reference_id ILIKE stem || '%'
--     OR d.claim_request_id ILIKE stem || '%' OR d.original_filename ILIKE stem || '%');
