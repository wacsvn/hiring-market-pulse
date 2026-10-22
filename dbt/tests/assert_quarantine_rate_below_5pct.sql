-- Some deleted posts are normal. A spike in rejections means the source or contract changed.
with q as (
    select count(*) as n from {{ ref('stg_quarantine') }} where dataset = 'hn_posts'
),

p as (
    select count(*) as n from {{ ref('stg_hn_posts') }}
)

select q.n as quarantined, p.n as accepted
from q cross join p
where q.n > 0.05 * (q.n + p.n)
