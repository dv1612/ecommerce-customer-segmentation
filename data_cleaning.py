"""
data_cleaning.py
----------------
Cleans the raw UCI Online Retail transactional extract and produces an
analysis-ready CSV for the RFM model.

Usage:
    python data_cleaning.py --input data/raw/online_retail.csv \
                            --output data/clean/online_retail_clean.csv
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

LOGGER = logging.getLogger("data_cleaning")

RAW_COLUMNS = [
    "InvoiceNo",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "UnitPrice",
    "CustomerID",
    "Country",
]

DTYPES = {
    "InvoiceNo": "string",
    "StockCode": "string",
    "Description": "string",
    "Quantity": "Int64",
    "UnitPrice": "float64",
    "CustomerID": "float64",   # read as float: the raw file stores blanks as NaN
    "Country": "string",
    "InvoiceDate": "string",   # parsed explicitly in parse_invoice_date()
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean the Online Retail dataset.")
    parser.add_argument("--input", required=True, help="Path to the raw CSV file.")
    parser.add_argument("--output", required=True, help="Path for the cleaned CSV file.")
    parser.add_argument("--encoding", default="ISO-8859-1", help="Raw file encoding.")
    parser.add_argument(
        "--chunksize",
        type=int,
        default=0,
        help="Optional chunk size for low-memory reads (0 = read in one pass).",
    )
    return parser.parse_args()


def load_raw(path: Path, encoding: str, chunksize: int) -> pd.DataFrame:
    """Read the raw CSV, with explicit dtypes and date parsing."""
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    read_kwargs = {
        "encoding": encoding,
        "dtype": DTYPES,
    }

    try:
        if chunksize and chunksize > 0:
            chunks = pd.read_csv(path, chunksize=chunksize, **read_kwargs)
            frame = pd.concat(chunks, ignore_index=True)
        else:
            frame = pd.read_csv(path, **read_kwargs)
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Could not decode {path} using '{encoding}'. Try --encoding utf-8."
        ) from exc
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"Input file is empty: {path}") from exc
    except pd.errors.ParserError as exc:
        raise ValueError(f"Malformed CSV at {path}: {exc}") from exc

    missing = [col for col in RAW_COLUMNS if col not in frame.columns]
    if missing:
        raise ValueError(f"Input file is missing required column(s): {missing}")

    return frame


def parse_invoice_date(series: pd.Series) -> pd.Series:
    """Parse InvoiceDate without assuming a layout.

    The UCI file ships as dd/mm/yyyy, while an Excel-to-CSV export is usually
    ISO. Forcing dayfirst=True on ISO input fails on any day > 12, so parse
    with pandas' inferred format first and only fall back to day-first when
    that genuinely produces fewer failures.
    """
    primary = pd.to_datetime(series, errors="coerce")
    bad_primary = int(primary.isna().sum())
    if bad_primary == 0:
        return primary

    fallback = pd.to_datetime(series, errors="coerce", dayfirst=True)
    if int(fallback.isna().sum()) < bad_primary:
        LOGGER.info("InvoiceDate parsed using day-first layout.")
        return fallback
    return primary


def clean(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the cleaning rules and log the row count removed at each step."""
    rows = len(frame)
    LOGGER.info("Rows loaded: %s", f"{rows:,}")

    def drop(df: pd.DataFrame, label: str) -> pd.DataFrame:
        nonlocal rows
        removed = rows - len(df)
        LOGGER.info("%-28s removed %8s | remaining %9s",
                    label, f"{removed:,}", f"{len(df):,}")
        rows = len(df)
        return df

    frame = drop(frame.drop_duplicates(), "exact duplicate rows")
    frame = drop(frame.dropna(subset=["CustomerID"]), "null CustomerID")
    frame = frame.copy()
    frame["InvoiceDate"] = parse_invoice_date(frame["InvoiceDate"])
    frame = drop(frame.dropna(subset=["InvoiceDate"]), "unparseable InvoiceDate")

    # Cancelled orders carry an InvoiceNo prefixed with 'C'.
    is_cancelled = frame["InvoiceNo"].str.strip().str.upper().str.startswith("C", na=False)
    frame = drop(frame.loc[~is_cancelled], "cancelled orders (C-prefix)")

    frame = drop(frame.loc[frame["Quantity"] > 0], "non-positive Quantity")
    frame = drop(frame.loc[frame["UnitPrice"] > 0], "non-positive UnitPrice")

    frame = frame.copy()
    frame["CustomerID"] = frame["CustomerID"].astype("int64")
    frame["InvoiceNo"] = frame["InvoiceNo"].str.strip()
    frame["StockCode"] = frame["StockCode"].str.strip()
    frame["Description"] = frame["Description"].str.strip()
    frame["Total_Price"] = (frame["Quantity"] * frame["UnitPrice"]).round(2)

    if frame.empty:
        raise ValueError("No rows survived cleaning - check the input file.")

    LOGGER.info(
        "Clean set: %s rows | %s customers | %s invoices | %s to %s",
        f"{len(frame):,}",
        f"{frame['CustomerID'].nunique():,}",
        f"{frame['InvoiceNo'].nunique():,}",
        frame["InvoiceDate"].min().date(),
        frame["InvoiceDate"].max().date(),
    )
    return frame


def export(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        frame.to_csv(path, index=False, date_format="%Y-%m-%d %H:%M:%S")
    except OSError as exc:
        raise OSError(f"Could not write output to {path}: {exc}") from exc
    LOGGER.info("Wrote %s", path.resolve())


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()
    try:
        raw = load_raw(Path(args.input), args.encoding, args.chunksize)
        clean_frame = clean(raw)
        export(clean_frame, Path(args.output))
    except (FileNotFoundError, ValueError, OSError) as exc:
        LOGGER.error("%s", exc)
        return 1
    except MemoryError:
        LOGGER.error("Out of memory - re-run with --chunksize 100000.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
