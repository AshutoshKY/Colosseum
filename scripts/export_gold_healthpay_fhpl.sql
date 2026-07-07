-- Colosseum ground-truth export — HEALTHPAY-AI, **test-fhpl branch** database.
-- For the numeric test-docs claims (26052628873, 260527..., 26052730517).
--
--   psql "$HEALTHPAY_FHPL_DATABASE_URL" -tA -f scripts/export_gold_healthpay_fhpl.sql \
--     > healthpay_fhpl_gold.jsonl
--
-- Schema per test-fhpl: documents has NO client_reference_id / claim_reference_id /
-- claim_request_id / policy_extraction columns — the numeric stem IS the claim_id
-- (filename 26052628873-1.pdf -> claim_id 26052628873), with original_filename as fallback.
--
-- What each field is:
--   segments  -> gold for the `segregation` task (document_segments: type + page_range)
--   extracted -> per-task production outputs from raw_extracted_data as an ARRAY (no
--                uniqueness on document_type; newest first): pharmacy_bills (merged bills
--                with per-item category -> itemized/consolidated + items_categorisation),
--                nme_analysis, audit_analysis, patient_summary, prescription, claim_forms...
--   review    -> review_sessions: original_payload (pure model output) vs edited_payload
--                (HUMAN-CORRECTED final = the real gold), newest first, with status.

WITH refs(stem) AS (
  VALUES
    ('26052628873'), ('26052729852'), ('26052729911'), ('26052729999'),
    ('26052730065'), ('26052730136'), ('26052730195'), ('26052730517')
),
matched AS (
  SELECT r.stem, d.id, d.claim_id, d.claim_type, d.original_filename
  FROM refs r
  JOIN documents d
    ON d.claim_id          ILIKE r.stem || '%'
    OR d.original_filename ILIKE r.stem || '%'
)
SELECT json_build_object(
  'source',            'healthpay-ai:test-fhpl',
  'stem',              m.stem,
  'claim_id',          m.claim_id,
  'claim_type',        m.claim_type,
  'original_filename', m.original_filename,
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

-- Sanity check — list stems with no match:
--   SELECT stem FROM (VALUES
--     ('26052628873'),('26052729852'),('26052729911'),('26052729999'),
--     ('26052730065'),('26052730136'),('26052730195'),('26052730517')) v(stem)
--   WHERE NOT EXISTS (SELECT 1 FROM documents d
--     WHERE d.claim_id ILIKE stem || '%' OR d.original_filename ILIKE stem || '%');
