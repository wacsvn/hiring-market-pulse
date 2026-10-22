-- One row per post from the extractor used for reporting. Phase 2 adds LLM extractors here
-- with a fallback to rules for posts the LLM hasn't processed yet.
select
    post_id,
    extractor,
    extractor_version,
    nullif(trim(company), '') as company,
    work_mode,
    role_families,
    element_at(role_families, 1) as primary_role_family,
    seniority,
    locations,
    cast(salary_min as bigint) as salary_min,
    cast(salary_max as bigint) as salary_max,
    salary_currency,
    salary_period,
    tech,
    visa_sponsorship
from {{ source('raw', 'extractions_rules') }}
