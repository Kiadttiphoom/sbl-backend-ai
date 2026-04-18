from typing import Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)

# Registration of SQL Templates
# Instead of letting LLM generate raw SQL, the LLM will output an intent + parameters.
# We then map that to these rigid, safe SQL queries.

SQL_TEMPLATES: Dict[str, str] = {
    "BRANCH_SUMMARY": "SELECT TOP 100 AccNo, Stat2, AccStat, Bal, Interest FROM LSM010 WHERE OLID = :branch_code",
    "PAID_UP_LIST": "SELECT TOP 100 AccNo FROM LSM010 WHERE AccStat = '1' AND (:branch_code IS NULL OR OLID = :branch_code)",
    "WARNING_GROUP": "SELECT TOP 100 AccNo, Stat2, Bal FROM LSM010 WHERE Stat2 IN ('B', 'C', 'D') AND (:branch_code IS NULL OR OLID = :branch_code)",
    "TOP_INTEREST": "SELECT TOP 5 AccNo, Interest FROM LSM010 ORDER BY Interest DESC",
    "TOTAL_BALANCE": "SELECT SUM(Bal + BalTax) AS TotalBalance FROM LSM010",
    "EMPLOYEE_PORTFOLIO": "SELECT TOP :limit LSM010.FolID, LSM007.FolName, SUM(LSM010.Bal + LSM010.BalTax) AS TotalBalance FROM LSM010 INNER JOIN LSM007 ON LSM010.FolID = LSM007.FolID GROUP BY LSM010.FolID, LSM007.FolName ORDER BY TotalBalance DESC"
}

def render_query(template_name: str, params: Dict[str, Any]) -> Tuple[str, list]:
    """
    Takes a template name and a dictionary of parameters, and returns the parameterized SQL string.
    Note: For a real MS SQL driver like pyodbc, we usually use `?` syntax. 
    Here we will construct a safe parameterized query.
    """
    if template_name not in SQL_TEMPLATES:
        raise ValueError(f"Unknown query template: {template_name}")
    
    query = SQL_TEMPLATES[template_name]
    
    # In a real environment, we should use bound parameters (the ? syntax for DBAPI).
    # Since the current fetch_data accepts raw SQL strings, we must inject safely.
    # THIS is still a prototype implementation of the template layer.
    
    for key, value in params.items():
        if value is None:
            # Simple handling for NULL injection (e.g. branch_code IS NULL)
            # In a robust system, use a query builder.
            pass
        elif isinstance(value, int):
            query = query.replace(f":{key}", str(value))
        else:
            # We sanitize the string just to be safe
            safe_val = str(value).replace("'", "''")
            query = query.replace(f":{key}", f"'{safe_val}'")
            
    # Clean up unprovided parameters for the specific templates logic
    query = query.replace("(:branch_code IS NULL OR OLID = :branch_code)", "1=1" if 'branch_code' not in params else f"OLID = '{params['branch_code']}'")
    
    return query, []
