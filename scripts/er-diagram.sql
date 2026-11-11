-- Prints a Mermaid erDiagram for the public schema (run with psql -tA).
WITH cols AS (
  SELECT c.table_name, c.column_name, c.ordinal_position,
         CASE
           WHEN c.data_type = 'USER-DEFINED' THEN c.udt_name
           WHEN c.data_type = 'timestamp with time zone' THEN 'timestamptz'
           WHEN c.data_type = 'character' THEN 'char'
           ELSE replace(c.data_type, ' ', '_')
         END AS typ,
         EXISTS (SELECT 1 FROM information_schema.table_constraints tc
                   JOIN information_schema.key_column_usage k USING (constraint_schema, constraint_name)
                  WHERE tc.constraint_type = 'PRIMARY KEY' AND k.table_name = c.table_name
                    AND k.column_name = c.column_name) AS is_pk,
         EXISTS (SELECT 1 FROM information_schema.table_constraints tc
                   JOIN information_schema.key_column_usage k USING (constraint_schema, constraint_name)
                  WHERE tc.constraint_type = 'FOREIGN KEY' AND k.table_name = c.table_name
                    AND k.column_name = c.column_name) AS is_fk,
         (SELECT p.category FROM pii_columns p
           WHERE p.table_name = c.table_name AND p.column_name = c.column_name) AS pii
    FROM information_schema.columns c
   WHERE c.table_schema = 'public' AND c.table_name <> 'alembic_version'
),
entities AS (
  SELECT table_name,
         '  ' || table_name || ' {' || chr(10) ||
         string_agg('    ' || typ || ' ' || column_name ||
                    CASE WHEN is_pk AND is_fk THEN ' PK,FK' WHEN is_pk THEN ' PK' WHEN is_fk THEN ' FK' ELSE '' END ||
                    CASE WHEN pii IS NOT NULL THEN ' "PII: ' || pii || '"' ELSE '' END,
                    chr(10) ORDER BY ordinal_position) || chr(10) || '  }' AS block
    FROM cols GROUP BY table_name
),
rels AS (
  SELECT DISTINCT ccu.table_name AS parent, kcu.table_name AS child, kcu.column_name AS col
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu USING (constraint_schema, constraint_name)
    JOIN information_schema.constraint_column_usage ccu USING (constraint_schema, constraint_name)
   WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
)
SELECT line FROM (
  SELECT 0 AS ord, 'erDiagram' AS line
  UNION ALL SELECT 1, block FROM entities
  UNION ALL SELECT 2, '  ' || parent || ' ||--o{ ' || child || ' : "' || col || '"' FROM rels
) x ORDER BY ord, line;
