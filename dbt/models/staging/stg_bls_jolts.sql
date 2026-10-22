select
    series_id,
    measure,
    month,
    value_thousands,
    is_preliminary
from {{ source('raw', 'bls_jolts') }}
