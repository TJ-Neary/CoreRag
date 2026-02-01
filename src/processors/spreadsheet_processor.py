"""
Spreadsheet Summary-to-Raw Pattern

Standard chunking destroys tabular data:
- Rows become meaningless comma-separated strings
- Column relationships are lost
- Numeric data loses context

This module:
1. Generates natural language summaries of spreadsheets
2. Indexes the summary for semantic search
3. Returns raw file path when summary matches
4. Claude reads the actual CSV/Excel for analysis
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any
import json

logger = logging.getLogger(__name__)


@dataclass
class SpreadsheetSummary:
    """Summary of a spreadsheet for indexing."""
    file_path: str
    file_name: str
    sheet_names: List[str]
    column_descriptions: Dict[str, str]  # column_name -> description
    row_count: int
    column_count: int
    summary_text: str
    key_statistics: Dict[str, Any]
    sample_rows: List[Dict]  # First few rows as dicts
    data_types: Dict[str, str]  # column -> type


class SpreadsheetAnalyzer:
    """
    Analyzes spreadsheets and generates searchable summaries.

    Usage:
        analyzer = SpreadsheetAnalyzer()
        summary = analyzer.analyze(Path("data.xlsx"))
        # Index summary.summary_text
        # When searched, return summary.file_path for Claude to read
    """

    SUMMARY_PROMPT = """Analyze this spreadsheet data and create a natural language summary.

Columns: {columns}
Row count: {row_count}
Sample data:
{sample_data}

Statistics:
{statistics}

Write a 2-3 paragraph summary describing:
1. What this data appears to be about
2. The main columns and what they contain
3. Any notable patterns or ranges in the data

Summary:"""

    def __init__(self, llm=None):
        """
        Args:
            llm: Local LLM for summary generation (optional)
        """
        self.llm = llm

    def analyze(self, file_path: Path) -> SpreadsheetSummary:
        """
        Analyze a spreadsheet and generate summary.

        Args:
            file_path: Path to CSV, XLS, or XLSX file

        Returns:
            SpreadsheetSummary for indexing
        """
        ext = file_path.suffix.lower()

        if ext == ".csv":
            return self._analyze_csv(file_path)
        elif ext in (".xls", ".xlsx", ".xlsm"):
            return self._analyze_excel(file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

    def _analyze_csv(self, file_path: Path) -> SpreadsheetSummary:
        """Analyze a CSV file."""
        import pandas as pd

        try:
            df = pd.read_csv(file_path, nrows=1000)  # Limit for analysis
        except Exception as e:
            logger.error(f"Failed to read CSV: {e}")
            raise

        return self._analyze_dataframe(df, file_path, ["Sheet1"])

    def _analyze_excel(self, file_path: Path) -> SpreadsheetSummary:
        """Analyze an Excel file."""
        import pandas as pd

        try:
            excel = pd.ExcelFile(file_path)
            sheet_names = excel.sheet_names

            # Analyze first/main sheet
            df = pd.read_excel(excel, sheet_name=0, nrows=1000)

        except Exception as e:
            logger.error(f"Failed to read Excel: {e}")
            raise

        return self._analyze_dataframe(df, file_path, sheet_names)

    def _analyze_dataframe(
        self,
        df,
        file_path: Path,
        sheet_names: List[str]
    ) -> SpreadsheetSummary:
        """Analyze a pandas DataFrame."""
        import pandas as pd

        # Column descriptions
        column_descriptions = {}
        for col in df.columns:
            dtype = str(df[col].dtype)
            nunique = df[col].nunique()
            null_count = df[col].isnull().sum()

            if pd.api.types.is_numeric_dtype(df[col]):
                desc = f"Numeric column ({dtype}), {nunique} unique values"
                if null_count == 0:
                    desc += f", range [{df[col].min():.2f}, {df[col].max():.2f}]"
            elif pd.api.types.is_datetime64_any_dtype(df[col]):
                desc = f"Date/time column"
            else:
                desc = f"Text column, {nunique} unique values"
                if nunique <= 10:
                    desc += f": {list(df[col].dropna().unique()[:5])}"

            column_descriptions[str(col)] = desc

        # Key statistics
        key_stats = {
            "row_count": len(df),
            "column_count": len(df.columns),
            "null_percentage": (df.isnull().sum().sum() / (len(df) * len(df.columns)) * 100),
        }

        # Add numeric column stats
        numeric_cols = df.select_dtypes(include=['number']).columns
        for col in numeric_cols[:5]:  # Limit to first 5
            key_stats[f"{col}_mean"] = df[col].mean()
            key_stats[f"{col}_median"] = df[col].median()

        # Sample rows
        sample_rows = df.head(5).to_dict(orient="records")

        # Data types
        data_types = {str(col): str(dtype) for col, dtype in df.dtypes.items()}

        # Generate summary text
        summary_text = self._generate_summary(
            df, column_descriptions, key_stats, file_path.name
        )

        return SpreadsheetSummary(
            file_path=str(file_path),
            file_name=file_path.name,
            sheet_names=sheet_names,
            column_descriptions=column_descriptions,
            row_count=len(df),
            column_count=len(df.columns),
            summary_text=summary_text,
            key_statistics=key_stats,
            sample_rows=sample_rows,
            data_types=data_types
        )

    def _generate_summary(
        self,
        df,
        column_descriptions: Dict[str, str],
        statistics: Dict[str, Any],
        file_name: str
    ) -> str:
        """Generate natural language summary."""
        import pandas as pd

        # Build summary components
        parts = []

        # File overview
        parts.append(
            f"This spreadsheet '{file_name}' contains {len(df)} rows and "
            f"{len(df.columns)} columns of data."
        )

        # Column summary
        col_list = ", ".join(df.columns[:10].tolist())
        if len(df.columns) > 10:
            col_list += f" (and {len(df.columns) - 10} more columns)"
        parts.append(f"Columns include: {col_list}.")

        # Numeric columns summary
        numeric_cols = df.select_dtypes(include=['number']).columns
        if len(numeric_cols) > 0:
            num_summary = []
            for col in numeric_cols[:3]:
                num_summary.append(
                    f"{col} (mean: {df[col].mean():.2f}, "
                    f"range: {df[col].min():.2f}-{df[col].max():.2f})"
                )
            parts.append(f"Numeric data includes: {'; '.join(num_summary)}.")

        # Categorical columns
        cat_cols = df.select_dtypes(include=['object']).columns
        if len(cat_cols) > 0:
            for col in cat_cols[:2]:
                unique_count = df[col].nunique()
                if unique_count <= 5:
                    values = list(df[col].dropna().unique())
                    parts.append(f"The '{col}' column has values: {values}.")
                else:
                    parts.append(f"The '{col}' column has {unique_count} unique values.")

        # Data quality
        null_pct = statistics.get("null_percentage", 0)
        if null_pct > 0:
            parts.append(f"Data completeness: {100-null_pct:.1f}% of cells have values.")

        return " ".join(parts)


class SpreadsheetIndexer:
    """
    Indexes spreadsheet summaries for search.

    When a summary matches, returns the file path so Claude can
    load and analyze the actual data.
    """

    def __init__(self, db, embedder, table_name: str = "spreadsheet_summaries"):
        self.db = db
        self.embedder = embedder
        self.table_name = table_name
        self._ensure_table()

    def _ensure_table(self):
        """Ensure the summaries table exists."""
        import pyarrow as pa

        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("file_path", pa.string()),
            pa.field("file_name", pa.string()),
            pa.field("summary_text", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 768)),
            pa.field("metadata", pa.string()),  # JSON with full summary
        ])

        try:
            self.db.open_table(self.table_name)
        except:
            self.db.create_table(self.table_name, schema=schema)

    async def index_spreadsheet(self, summary: SpreadsheetSummary) -> str:
        """
        Index a spreadsheet summary.

        Args:
            summary: SpreadsheetSummary to index

        Returns:
            Document ID
        """
        import uuid

        # Embed the summary text
        vector = await self.embedder(summary.summary_text)

        # Create document
        doc_id = str(uuid.uuid4())
        doc = {
            "id": doc_id,
            "file_path": summary.file_path,
            "file_name": summary.file_name,
            "summary_text": summary.summary_text,
            "vector": vector,
            "metadata": json.dumps({
                "sheet_names": summary.sheet_names,
                "column_descriptions": summary.column_descriptions,
                "row_count": summary.row_count,
                "column_count": summary.column_count,
                "key_statistics": summary.key_statistics,
                "data_types": summary.data_types,
            })
        }

        table = self.db.open_table(self.table_name)
        table.add([doc])

        logger.info(f"Indexed spreadsheet: {summary.file_name}")
        return doc_id

    async def search(
        self,
        query: str,
        k: int = 5
    ) -> List[Dict]:
        """
        Search for spreadsheets matching query.

        Returns file paths that Claude should load for analysis.
        """
        vector = await self.embedder(query)

        table = self.db.open_table(self.table_name)
        results = table.search(vector).limit(k).to_list()

        return [
            {
                "file_path": r["file_path"],
                "file_name": r["file_name"],
                "summary": r["summary_text"],
                "score": r.get("_distance", 0),
                "metadata": json.loads(r.get("metadata", "{}"))
            }
            for r in results
        ]


# MCP tool for spreadsheet access
def create_spreadsheet_tool(indexer: SpreadsheetIndexer):
    """Create MCP tool for spreadsheet search."""

    async def search_spreadsheets(query: str, k: int = 3) -> Dict:
        """
        Search for spreadsheets by content description.

        Returns file paths - use read_dataframe tool to load actual data.
        """
        results = await indexer.search(query, k)

        return {
            "results": results,
            "instruction": (
                "These are spreadsheet summaries. To analyze the actual data, "
                "use the read_dataframe tool with the file_path from results."
            )
        }

    return search_spreadsheets
