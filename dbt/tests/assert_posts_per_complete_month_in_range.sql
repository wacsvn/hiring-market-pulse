-- A complete month with too few or too many posts usually means a broken fetch or a parsing
-- change upstream, not a real market move.
select thread_month, postings
from {{ ref('mart_monthly_summary') }}
where is_complete_month
  and (postings < {{ env_var('PULSE_MIN_POSTS_PER_MONTH', '100') }} or postings > {{ var('max_posts_per_month') }})
