-- A complete month with too few or too many posts usually means a broken fetch or a parsing
-- change upstream, not a real market move. Counts start from the threads, so a thread whose
-- fetch came back empty shows up as 0 posts instead of silently dropping out of the check.
with counts as (
    select t.thread_month, count(p.post_id) as postings
    from {{ ref('stg_hn_threads') }} as t
    left join {{ ref('stg_hn_posts') }} as p using (thread_id)
    where t.thread_month < date_trunc('month', current_date())
    group by t.thread_month
)

select thread_month, postings
from counts
where postings < {{ env_var('PULSE_MIN_POSTS_PER_MONTH', '100') }}
   or postings > {{ var('max_posts_per_month') }}
