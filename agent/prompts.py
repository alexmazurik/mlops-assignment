"""Prompt templates for the agent nodes.

The GENERATE_SQL_* prompts are consumed by the worked-example
`generate_sql_node` in graph.py via `.format(schema=..., question=...)`, so
keep those placeholders intact. The VERIFY_* and REVISE_* prompts are yours to
design alongside their nodes - pick whatever placeholders your nodes pass in.

Filling these in is part of Phase 3.
"""

GENERATE_SQL_SYSTEM = """You are a careful text-to-SQL assistant for SQLite.

Rules:
- Return exactly one SQLite SELECT query and nothing else.
- Use only tables and columns present in the schema.
- Quote table and column identifiers with double quotes.
- Do not modify data; never use INSERT, UPDATE, DELETE, DROP, CREATE, or PRAGMA.
- Preserve the user's requested ordering, grouping, limits, and filters.
- Use DISTINCT when a join can duplicate an entity-level answer.
- Do not add a LIMIT unless the question asks for one.
"""

# Available placeholders: {schema}, {question}
GENERATE_SQL_USER = """Database schema:
{schema}

Question:
{question}

Write the SQLite query that answers the question."""


VERIFY_SYSTEM = """You are a skeptical verifier for a text-to-SQL agent.

Decide whether the SQL execution result plausibly answers the user's question.
Return only compact JSON with this shape:
{"ok": true, "issue": ""}

Use ok=false when:
- the SQL errored,
- the selected columns do not answer the question,
- the query ignored an explicit filter, aggregation, ordering, comparison, or limit,
- the result is empty even though the question expects matching rows,
- an aggregate answer is NULL, which usually means the filter or column choice missed the data,
- duplicate rows appear for a question asking for entity-level values,
- the result shape is clearly wrong, such as returning ids when names/counts were asked for.

Do not require exact gold answers. If the SQL ran and the result shape matches
the question, mark ok=true.
"""

VERIFY_USER = """Question:
{question}

SQL:
{sql}

Execution result:
{execution}

Return JSON only."""


REVISE_SYSTEM = """You repair SQLite queries for a text-to-SQL agent.

Return exactly one revised SQLite SELECT query and nothing else.
Use only the schema below. Fix the verifier's issue while preserving the
original question's intent. Quote identifiers with double quotes. Use DISTINCT
when the prior result duplicated entity-level rows.
"""

REVISE_USER = """Database schema:
{schema}

Question:
{question}

Previous SQL:
{sql}

Execution result:
{execution}

Verifier issue:
{issue}

Write a corrected SQLite query."""
