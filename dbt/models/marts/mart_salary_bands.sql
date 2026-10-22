-- USD annual salary distribution by role family and seniority over the trailing 12 months.
-- Grain: primary_role_family x seniority. Small groups are kept but flagged.
with recent as (
    select *
    from {{ ref('fct_postings') }}
    where salary_usd_annual_mid is not null
      and thread_month > add_months((select max(thread_month) from {{ ref('fct_postings') }}), -12)
)

select
    primary_role_family,
    seniority,
    count(*) as sample_size,
    count(*) >= 20 as is_reliable,
    percentile_approx(salary_usd_annual_mid, 0.25) as p25_usd,
    percentile_approx(salary_usd_annual_mid, 0.5) as median_usd,
    percentile_approx(salary_usd_annual_mid, 0.75) as p75_usd
from recent
group by primary_role_family, seniority
