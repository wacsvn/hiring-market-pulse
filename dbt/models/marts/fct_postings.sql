-- One row per job post with its extracted fields. Grain: post_id.
select
    p.post_id,
    p.thread_month,
    p.posted_at,
    e.company,
    e.work_mode,
    e.role_families,
    coalesce(e.primary_role_family, 'other') as primary_role_family,
    e.seniority,
    e.locations,
    e.tech,
    e.visa_sponsorship,
    e.salary_min,
    e.salary_max,
    e.salary_currency,
    e.salary_period,
    e.salary_min is not null as has_salary,
    -- Comparable salary: USD annual only, midpoint of the posted range.
    case
        when e.salary_currency = 'USD' and e.salary_period = 'year'
            then (e.salary_min + e.salary_max) / 2.0
    end as salary_usd_annual_mid,
    e.extractor,
    p.thread_month < date_trunc('month', current_date()) as is_complete_month
from {{ ref('stg_hn_posts') }} as p
inner join {{ ref('stg_extractions') }} as e using (post_id)
