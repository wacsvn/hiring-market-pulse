-- How often each technology is mentioned, per month. Grain: month x tech.
with exploded as (
    select thread_month, post_id, explode(tech) as tech
    from {{ ref('fct_postings') }}
),

totals as (
    select thread_month, count(*) as month_postings
    from {{ ref('fct_postings') }}
    group by thread_month
)

select
    e.thread_month,
    e.tech,
    count(distinct e.post_id) as postings,
    count(distinct e.post_id) / t.month_postings as share_of_postings
from exploded as e
inner join totals as t using (thread_month)
group by e.thread_month, e.tech, t.month_postings
