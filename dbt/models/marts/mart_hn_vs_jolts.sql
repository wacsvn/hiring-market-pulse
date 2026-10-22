-- HN posting volume vs official BLS JOLTS Information-sector openings, on overlapping months.
-- Both series are indexed to 100 at the first common month so their shapes can be compared.
-- Grain: month.
with hn as (
    select thread_month as month, count(*) as hn_postings
    from {{ ref('fct_postings') }}
    where is_complete_month
    group by thread_month
),

jolts as (
    select
        month,
        max(case when measure = 'openings' then value_thousands end) as jolts_openings_k,
        max(case when measure = 'hires' then value_thousands end) as jolts_hires_k,
        max(case when measure = 'quits' then value_thousands end) as jolts_quits_k,
        max(cast(is_preliminary as int)) = 1 as jolts_is_preliminary
    from {{ ref('stg_bls_jolts') }}
    group by month
),

joined as (
    select *
    from hn
    inner join jolts using (month)
),

indexed as (
    select
        *,
        100.0 * hn_postings / first_value(hn_postings) over (order by month) as hn_index,
        100.0 * jolts_openings_k / first_value(jolts_openings_k) over (order by month)
            as jolts_openings_index,
        100.0 * (hn_postings / lag(hn_postings) over (order by month) - 1) as hn_mom_pct,
        100.0 * (jolts_openings_k / lag(jolts_openings_k) over (order by month) - 1)
            as jolts_mom_pct
    from joined
)

select
    *,
    -- A big move in one series that the other doesn't echo: worth a look, not necessarily wrong.
    coalesce(
        (abs(hn_mom_pct) >= {{ var('divergence_threshold_pct') }}
            and abs(jolts_mom_pct) < {{ var('divergence_threshold_pct') }} / 2)
        or (abs(jolts_mom_pct) >= {{ var('divergence_threshold_pct') }}
            and abs(hn_mom_pct) < {{ var('divergence_threshold_pct') }} / 2)
        or (sign(hn_mom_pct) != sign(jolts_mom_pct)
            and abs(hn_mom_pct) >= {{ var('divergence_threshold_pct') }}
            and abs(jolts_mom_pct) >= {{ var('divergence_threshold_pct') }}),
        false
    ) as is_divergent
from indexed
