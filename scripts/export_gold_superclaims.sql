-- Colosseum ground-truth export — run against the SUPERCLAIMS-AI database.
--
--   psql "$SUPERCLAIMS_DATABASE_URL" -tA -f scripts/export_gold_superclaims.sql \
--     > superclaims_gold.jsonl
--
-- One JSON object per line per matched claim. Covers the NON-numeric test-docs stems
-- (numeric ones are healthpay test-fhpl claims — see export_gold_healthpay_fhpl.sql).
-- Matches against claim_id / client_reference_id / claim_reference_id (prefix match).
--
-- What each field is:
--   segments   -> gold for the `segregation` task (claims.segments JSON)
--   extracted  -> per-task production outputs from extracted_data, keyed by document_type:
--                 pharmacy_bills (merged bills WITH per-item category -> itemized/consolidated
--                 + items_categorisation gold), nme_analysis, audit_analysis, patient_summary,
--                 claim_forms, prescription, icd_codes, ...
--   review     -> review_sessions: original_payload (pure model output) vs edited_payload
--                 (HUMAN-CORRECTED final = the real gold), newest first, with status.

WITH refs(stem) AS (
  VALUES
    ('E9TNRZBK'),    ('REQ65CYP9E0'), ('REQ7FSWENTC'), ('REQ9LQ8EMUG'),
    ('REQB3A0ZPJV'), ('REQC183P024'), ('REQG9M0IPNB'), ('REQGCHOM85Q'),
    ('REQN4LFJ5QW'), ('REQRM38KJOF'), ('REQSG1CBFKW'), ('REQTWKX8N5C'),
    ('REQVS8XQ3FA'), ('REQW3D6S728'), ('REQWJ74XVTG'), ('REQXFCYR1DT'),
    ('T14SBYEU'),    ('XCAS2J1V')
),
matched AS (
  SELECT r.stem, c.id, c.claim_id, c.claim_type, c.segments
  FROM refs r
  JOIN claims c
    ON c.claim_id             ILIKE r.stem || '%'
    OR c.client_reference_id  ILIKE r.stem || '%'
    OR c.claim_reference_id   ILIKE r.stem || '%'
)
SELECT json_build_object(
  'source',     'superclaims-ai',
  'stem',       m.stem,
  'claim_id',   m.claim_id,
  'claim_type', m.claim_type,
  'segments',   m.segments,
  'extracted',  (SELECT json_object_agg(ed.document_type, ed.json_data)
                 FROM extracted_data ed
                 WHERE ed.claim_id = m.id),
  'review',     (SELECT json_agg(json_build_object(
                          'status',           rs.status,
                          'submitted_at',     rs.submitted_at,
                          'original_payload', rs.original_payload,
                          'edited_payload',   rs.edited_payload)
                        ORDER BY rs.updated_at DESC)
                 FROM review_sessions rs
                 WHERE rs.claim_id = m.id)
)
FROM matched m;

-- Sanity check (run separately if the main query returns few rows):
--   SELECT stem FROM (VALUES ('E9TNRZBK'),('REQ65CYP9E0')) v(stem)
--   WHERE NOT EXISTS (SELECT 1 FROM claims c WHERE c.claim_id ILIKE stem || '%'
--     OR c.client_reference_id ILIKE stem || '%' OR c.claim_reference_id ILIKE stem || '%');
