select dataset, record_key, reason, quarantined_at
from {{ source('raw', 'quarantine') }}
