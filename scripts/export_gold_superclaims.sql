-- Colosseum ground-truth export — run against the SUPERCLAIMS-AI (v2) database.
--
--   psql "$SUPERCLAIMS_DATABASE_URL" -tA -f scripts/export_gold_superclaims.sql \
--     > superclaims_gold.jsonl
--
-- One JSON object per line per matched claim. Covers:
--   1. patient summary       -> extracted_data.patient_summary / review.edited_payload.patient_summary
--   2. cheque bank           -> extracted_data.cheque_or_bank_details / review.edited_payload.bank_details
--   3. bills and items       -> extracted_data.pharmacy_bills (itemized / consolidated) / review.edited_payload.bill_data
--   4. item categorisation   -> extracted_data.nme_analysis (categorized bills) / review.edited_payload.nme_analysis
--   5. segregation           -> claims.segments JSON (document segments with types & page ranges)
--   6. nme                   -> review.edited_payload.nme_analysis (is_nme items, policy violations)
--   7. benefit plan          -> review.edited_payload.benefit_plan_breakdown / extracted_data.benefit_plan / claims.doc_details.benefits
--   8. prescription          -> extracted_data.prescription (claims_digitization_details)
--   9. audit                 -> review.edited_payload.audit_analysis (human-corrected) / extracted_data.audit_analysis
--  10. icd 10 codes          -> extracted_data.icd_codes / review.edited_payload.icd_codes
--  11. policy extraction     -> claims.doc_details (policy, policy_details, policy_rules) / review.edited_payload.policy_extraction
--
-- Matches against claim_id / client_reference_id / claim_reference_id (prefix match).

WITH refs(stem) AS (
  VALUES
    ('E9TNRZBK'),    ('REQ65CYP9E0'), ('REQ7FSWENTC'), ('REQ9LQ8EMUG'),
    ('REQB3A0ZPJV'), ('REQC183P024'), ('REQG9M0IPNB'), ('REQGCHOM85Q'),
    ('REQN4LFJ5QW'), ('REQRM38KJOF'), ('REQSG1CBFKW'), ('REQTWKX8N5C'),
    ('REQVS8XQ3FA'), ('REQW3D6S728'), ('REQWJ74XVTG'), ('REQXFCYR1DT'),
    ('T14SBYEU'),    ('XCAS2J1V')
),
matched AS (
  SELECT
    r.stem,
    c.id,
    c.claim_id,
    c.claim_type,
    c.segments,
    c.doc_details,
    c.client_reference_id,
    c.claim_reference_id,
    c.user_id,
    c.dependent_id,
    c.insurer_name,
    c.company_name,
    c.created_at
  FROM refs r
  JOIN claims c
    ON c.claim_id             ILIKE r.stem || '%'
    OR c.client_reference_id  ILIKE r.stem || '%'
    OR c.claim_reference_id   ILIKE r.stem || '%'
)
SELECT json_build_object(
  'source',              'superclaims-ai:v2',
  'stem',                m.stem,
  'claim_id',            m.claim_id,
  'claim_type',          m.claim_type,
  'client_reference_id', m.client_reference_id,
  'claim_reference_id',  m.claim_reference_id,
  'user_id',             m.user_id,
  'dependent_id',        m.dependent_id,
  'insurer_name',        m.insurer_name,
  'company_name',        m.company_name,
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
FROM matched m;

-- Sanity check (run separately if the main query returns few rows):
--   SELECT stem FROM (VALUES ('E9TNRZBK'),('REQ65CYP9E0')) v(stem)
--   WHERE NOT EXISTS (SELECT 1 FROM claims c WHERE c.claim_id ILIKE stem || '%'
--     OR c.client_reference_id ILIKE stem || '%' OR c.claim_reference_id ILIKE stem || '%');

