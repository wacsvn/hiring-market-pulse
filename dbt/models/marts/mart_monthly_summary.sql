-- Headline KPIs per thread month. Grain: thread_month.
-- Shares use doubles: plain 1.0 is DECIMAL and avg() rounds it to 5 places, which made
-- remote + hybrid + onsite add up to 1.00001 for some months.
select
    thread_month,
    is_complete_month,
    count(*) as postings,
    avg(case when work_mode = 'remote' then cast(1 as double) else cast(0 as double) end) as share_remote,
    avg(case when work_mode = 'hybrid' then cast(1 as double) else cast(0 as double) end) as share_hybrid,
    avg(case when work_mode = 'onsite' then cast(1 as double) else cast(0 as double) end) as share_onsite,
    avg(case when has_salary then cast(1 as double) else cast(0 as double) end) as share_with_salary,
    {{ percentile("salary_usd_annual_mid", 0.5) }} as median_salary_usd,
    count(salary_usd_annual_mid) as salary_sample_size,
    avg(case when visa_sponsorship then cast(1 as double) else cast(0 as double) end) as share_visa_sponsorship_mentioned
from {{ ref('fct_postings') }}
group by thread_month, is_complete_month
