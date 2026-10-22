select
    thread_id,
    title,
    thread_month,
    posted_at
from {{ source('raw', 'hn_threads') }}
