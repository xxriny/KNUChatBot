import io
import pandas as pd
from azure.storage.blob import BlobClient
from scripts.configs.storage_config import get_blob_config

def load_notices_df_from_blob(encoding: str = "utf-8") -> pd.DataFrame:
    cfg = get_blob_config()
    print(cfg.account_url)
    print(cfg.blob_name)
    print(cfg.container)
    print(cfg.credential)
    blob = BlobClient(
        account_url=cfg.account_url,
        container_name=cfg.container,
        blob_name=cfg.blob_name,
        credential=cfg.credential
    )
    data = blob.download_blob().readall()
    df = pd.read_csv(io.BytesIO(data), encoding=encoding)
    return df
