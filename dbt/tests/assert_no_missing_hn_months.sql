-- Every month between the first and last thread must have a thread.
with bounds as (
    select min(thread_month) as lo, max(thread_month) as hi from {{ ref('stg_hn_threads') }}
),

expected as (
    select explode(sequence(lo, hi, interval 1 month)) as month from bounds
)

select e.month
from expected as e
left join {{ ref('stg_hn_threads') }} as t on t.thread_month = e.month
where t.thread_id is null
