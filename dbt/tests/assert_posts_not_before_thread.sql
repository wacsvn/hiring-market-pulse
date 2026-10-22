-- A reply can't predate the thread it was posted in; if it does, ids or timestamps are mixed up.
select p.post_id, p.posted_at, t.posted_at as thread_posted_at
from {{ ref('stg_hn_posts') }} as p
inner join {{ ref('stg_hn_threads') }} as t using (thread_id)
where p.posted_at < t.posted_at
