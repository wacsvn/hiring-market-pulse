-- Headline KPIs per thread month. Grain: thread_month.
select
    thread_month,
    is_complete_month,
    count(*) as postings,
    avg(case when work_mode = 'remote' then 1.0 else 0 end) as share_remote,
    avg(case when work_mode = 'hybrid' then 1.0 else 0 end) as share_hybrid,
    avg(case when work_mode = 'onsite' then 1.0 else 0 end) as share_onsite,
    avg(case when has_salary then 1.0 else 0 end) as share_with_salary,
    percentile_approx(salary_usd_annual_mid, 0.5) as median_salary_usd,
    count(salary_usd_annual_mid) as salary_sample_size,
    avg(case when visa_sponsorship then 1.0 else 0 end) as share_visa_sponsorship_mentioned
from {{ ref('fct_postings') }}
group by thread_month, is_complete_month
