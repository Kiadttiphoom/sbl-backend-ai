import re

def get_relevant_schema(query: str, schema: dict) -> str:
    """
    Dynamic Schema Pruning:
    Selects only columns relevant to the user's query to reduce token count.
    Relies on JSON metadata (is_mandatory, descriptions).
    """
    query_clean = re.sub(r'[^\w\s]', ' ', query.lower())
    keywords = set(query_clean.split())
    
    relevant_schema = {}
    for table, info in schema.items():
        table_desc = info.get("description", "").lower()
        # If the table's description matches any keyword, include all its columns
        table_matches = any(kw in table_desc for kw in keywords)
        
        relevant_columns = {}
        for name, col in info.get("columns", {}).items():
            desc = col.get("desc", "").lower()
            
            # Inclusion Criteria: PK, Mandatory, or Keyword Match (Name/Desc/Table Match)
            is_relevant = (
                col.get("is_mandatory") or 
                col.get("is_pk") or 
                any(kw in name.lower() for kw in keywords) or
                any(kw in desc for kw in keywords) or
                table_matches
            )

            if is_relevant:
                relevant_columns[name] = col
        
        if relevant_columns:
            relevant_schema[table] = {
                "description": info.get("description"),
                "columns": relevant_columns
            }
    
    return get_compact_schema(relevant_schema)

def get_compact_schema(schema: dict) -> str:
    """
    Ultra-High Density Schema Formatter.
    Format: [Table]: ColName[PK]:Desc(Ex:x)[A=val|B=val]
    - options are read dynamically from the JSON metadata.
    """
    text = ""
    for table, info in schema.items():
        text += f"[{table}]: "
        cols = []
        # Sort columns to maintain deterministic output
        sorted_cols = sorted(info.get("columns", {}).items())
        for name, col in sorted_cols:
            pk = "*" if col.get("is_pk") else ""
            ex = f"(Ex:{col.get('example')})" if col.get("example") else ""
            desc = (col.get("desc") or "")[:35]

            # Dynamic options from JSON - reading mappings for status codes
            opts = col.get("options")
            if opts and isinstance(opts, dict):
                opt_str = "|".join(f"{k}={str(v)[:14]}" for k, v in opts.items())
                opts_part = f"[{opt_str}]"
            else:
                opts_part = ""

            cols.append(f"{name}{pk}:{desc}{ex}{opts_part}")
        text += " | ".join(cols) + "\n"
    return text
