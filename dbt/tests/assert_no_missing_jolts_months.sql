-- Each JOLTS series must be continuous from its first to its last month.
with bounds as (
    select measure, min(month) as lo, max(month) as hi
    from {{ ref('stg_bls_jolts') }}
    group by measure
),

expected as (
    select measure, explode(sequence(lo, hi, interval 1 month)) as month from bounds
)

select e.measure, e.month
from expected as e
left join {{ ref('stg_bls_jolts') }} as j using (measure, month)
where j.series_id is null
