select
    post_id,
    thread_id,
    thread_month,
    posted_at,
    author,
    text_html,
    length(text_html) as text_length
from {{ source('raw', 'hn_posts') }}
