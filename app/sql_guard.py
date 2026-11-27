"""Guardrails for LLM-written SQL, enforced in code before anything runs.

    check_sql("SELECT count(*) FROM building_permits")
    -> "SELECT COUNT(*) FROM building_permits LIMIT 500"   (safe, with a row limit)
    check_sql("DROP TABLE building_permits")
    -> raises UnsafeSQL("only SELECT queries are allowed (got Drop)")

The SQL is parsed into a tree with sqlglot (a SQL parser), not matched with
regular expressions: a parser knows that "-- ; DROP TABLE t" is a comment and
that "SELECT ... INTO t" creates a table, where a regex can be fooled.

This is one of three layers. Even if a query got past it, the database would
still refuse to write: the agent connects as the read-only civic_reader role,
in a READ ONLY transaction, with a statement timeout (app/db.py).
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

ALLOWED_TABLES = {"service_requests_311", "building_violations", "building_permits"}

# Functions are ALLOW-LISTED: only what counting and summarizing needs. Anything else
# (pg_sleep, pg_read_file, dblink, inet_server_addr, version, database_to_xml,
# generate_series, and any function nobody thought of) is refused. A deny-list only
# blocks the dangers someone listed; an allow-list also blocks the ones nobody listed.
# Names are as sqlglot reports them: it also treats AND/OR/CASE/IF/CAST as functions,
# and calls date_trunc "timestamp_trunc" and to_char "time_to_str".
ALLOWED_FUNCTIONS = {
    # logic and types
    "and", "or", "xor", "case", "if", "coalesce", "nullif", "cast", "try_cast", "greatest", "least",
    # aggregates
    "count", "sum", "avg", "min", "max", "percentile_cont", "percentile_disc", "median", "mode",
    "stddev", "stddev_pop", "stddev_samp", "variance", "var_pop", "var_samp", "corr",
    "array_agg", "string_agg", "group_concat", "count_if", "bool_and", "bool_or", "any_value",
    # window functions
    "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile", "lag", "lead",
    "first_value", "last_value", "nth_value",
    # dates
    "extract", "timestamp_trunc", "date_trunc", "time_to_str", "to_char", "date_part", "age",
    "make_date", "str_to_date", "str_to_time", "to_date", "to_timestamp", "date", "date_add",
    "date_sub", "date_diff", "datediff", "timestamp_add", "timestamp_sub", "timestamp_diff",
    "current_date", "current_timestamp", "interval",
    # text
    "lower", "upper", "length", "char_length", "substring", "trim", "ltrim", "rtrim", "concat",
    "concat_ws", "replace", "split_part", "left", "right", "initcap", "str_position", "position",
    "regexp_like", "regexp_i_like", "regexp_replace", "regexp_extract", "starts_with", "lpad", "rpad",
    # math
    "round", "floor", "ceil", "abs", "sign", "sqrt", "pow", "power", "ln", "log", "exp", "mod",
    "div", "safe_divide", "trunc",
}
# Functions allowed in FROM, which sqlglot represents as tables
# (a month series for counts that include empty months; its size is capped by the 15 s timeout)
TABLE_FUNCTIONS = {"generate_series", "exploding_generate_series", "unnest", "explode"}

# Anything that writes, changes the schema, or controls the session
FORBIDDEN_NODES = (exp.DML, exp.DDL, exp.Command, exp.Copy, exp.Set, exp.Transaction,
                   exp.Commit, exp.Grant, exp.Into, exp.Lock, exp.Insert, exp.Update,
                   exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter, exp.TruncateTable)


class UnsafeSQL(ValueError):
    """The query was rejected before running. The message says why."""


def _parse_one(sql: str) -> exp.Expression:
    try:
        trees = [t for t in sqlglot.parse(sql, read="postgres") if t is not None]
    except SqlglotError as e:  # ParseError, TokenError (e.g. an unclosed quote), ...
        raise UnsafeSQL(f"could not parse the SQL: {str(e).splitlines()[0]}") from None
    if len(trees) != 1:
        raise UnsafeSQL(f"exactly one statement is allowed (got {len(trees)})")
    return trees[0]


def _function_name(node: exp.Func) -> str:
    return (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()


def check_tree(tree: exp.Expression) -> None:
    if not isinstance(tree, exp.Query):
        raise UnsafeSQL(f"only SELECT queries are allowed (got {type(tree).__name__})")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            what = "SELECT ... INTO" if isinstance(node, exp.Into) else \
                   "FOR UPDATE / FOR SHARE" if isinstance(node, exp.Lock) else type(node).__name__
            raise UnsafeSQL(f"{what} is not allowed")
        # (a function used as a table in FROM is checked against TABLE_FUNCTIONS below)
        if isinstance(node, exp.Func) and not isinstance(node.parent, exp.Table) \
                and _function_name(node) not in ALLOWED_FUNCTIONS:
            raise UnsafeSQL(f"function {_function_name(node)}() is not allowed")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if isinstance(table.this, exp.Func):
            if _function_name(table.this) not in TABLE_FUNCTIONS:
                raise UnsafeSQL(f"function {_function_name(table.this)}() is not allowed in FROM")
            continue
        name, schema = table.name.lower(), table.db.lower()
        if schema and schema != "public":
            raise UnsafeSQL(f"schema {schema} is not allowed; use only {sorted(ALLOWED_TABLES)}")
        if name not in ALLOWED_TABLES and name not in cte_names:
            raise UnsafeSQL(f"unknown table {name}; use only {sorted(ALLOWED_TABLES)}")


def with_row_limit(tree: exp.Query, row_limit: int) -> exp.Query:
    """Add LIMIT row_limit if there's none; lower a LIMIT that's bigger."""
    limit = tree.args.get("limit")
    if limit is None:
        return tree.limit(row_limit)
    value = limit.expression
    if not (isinstance(value, exp.Literal) and value.is_int):
        raise UnsafeSQL("LIMIT must be a plain number")
    return tree.limit(row_limit) if int(value.this) > row_limit else tree


def check_sql(sql: str, row_limit: int = 500) -> str:
    """Safe, limited SQL to run, or UnsafeSQL. Comments are removed."""
    tree = _parse_one(sql)
    check_tree(tree)
    return with_row_limit(tree, row_limit).sql(dialect="postgres", comments=False)


def is_safe_select(sql: str) -> bool:
    try:
        check_sql(sql)
        return True
    except UnsafeSQL:
        return False
