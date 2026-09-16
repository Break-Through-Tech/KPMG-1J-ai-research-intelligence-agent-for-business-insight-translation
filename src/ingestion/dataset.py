#for loading merging and saving the papers, dedup and incremental skips
#creates a parquet for the chunking, embedding, vector database to then work off of

import os
from pathlib import Path
import pandas as pd

#put all current information into a pd
def load_existing(dataset_path):
    if os.path.exists(dataset_path):
        try: 
            return pd.read_parquet(dataset_path)
        except Exception as e: #if there is an error, we want to raise it asap
            raise RuntimeError(f"Could not load existing dataset at {dataset_path}: {e}") from e
    else:
        return pd.DataFrame()


#get the ids of the arxiv papers already ingested
def get_ingested_ids(existing_df):
    if existing_df.empty:
        return set()
    complete = existing_df[existing_df["ingestion_status"] == complete]
    return set(complete["arxiv_id"])


#merge current and old papers and save this
def merge_and_save(existing_df, new_rows, dataset_path):
    new_df = pd.DataFrame(new_rows)
    new_df["ingestion_status"] = new_df.apply(compute_ingestion_status, axis=1)
    combined = pd.concat([existing_df, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset="arxiv_id", keep="last")
    combined.to_parquet(dataset_path, index=False)
    return combined

def compute_ingestion_status(row):
    if row["download_status"] in ("downloaded", "skipped_exists"):
        if row["extraction_status"] == "extracted":
            return "complete"
        else:
            return "partial"
    else:
        return "failed"
