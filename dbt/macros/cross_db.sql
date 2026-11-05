{#
  The models are written for Databricks (Spark SQL). These macros cover the few functions
  DuckDB spells differently, so the same models and tests also run on the DuckDB fallback
  that the refresh uses when Databricks is unavailable. default__ is the Databricks form.
#}

{# One row per array element (Spark: explode). #}
{% macro unnest_array(array) %}{{ return(adapter.dispatch('unnest_array')(array)) }}{% endmacro %}
{% macro default__unnest_array(array) %}explode({{ array }}){% endmacro %}
{% macro duckdb__unnest_array(array) %}unnest({{ array }}){% endmacro %}

{# First element of an array, or null when it is empty. #}
{% macro first_element(array) %}{{ return(adapter.dispatch('first_element')(array)) }}{% endmacro %}
{% macro default__first_element(array) %}element_at({{ array }}, 1){% endmacro %}
{% macro duckdb__first_element(array) %}{{ array }}[1]{% endmacro %}

{# One row per month from lo to hi inclusive, as dates. #}
{% macro month_series(lo, hi) %}{{ return(adapter.dispatch('month_series')(lo, hi)) }}{% endmacro %}
{% macro default__month_series(lo, hi) %}explode(sequence({{ lo }}, {{ hi }}, interval 1 month)){% endmacro %}
{% macro duckdb__month_series(lo, hi) %}unnest(generate_series({{ lo }}, {{ hi }}, interval 1 month))::date{% endmacro %}

{# A percentile that is an actual value from the data, like Spark's percentile_approx. #}
{% macro percentile(expr, p) %}{{ return(adapter.dispatch('percentile')(expr, p)) }}{% endmacro %}
{% macro default__percentile(expr, p) %}percentile_approx({{ expr }}, {{ p }}){% endmacro %}
{% macro duckdb__percentile(expr, p) %}quantile_disc({{ expr }}, {{ p }}){% endmacro %}
