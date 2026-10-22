{{ config(severity='warn') }}
-- Signal, not failure: months where HN volume and official openings move very differently.
select month, hn_mom_pct, jolts_mom_pct
from {{ ref('mart_hn_vs_jolts') }}
where is_divergent
