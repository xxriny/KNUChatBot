import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()

@dataclass
class BlobStorageConfig:
    account_url: str
    container: str
    blob_name: str
    credential: str  # account key or SAS token

def get_blob_config() -> BlobStorageConfig:
    return BlobStorageConfig(
        account_url=os.getenv("AZURE_BLOB_ACCOUNT_URL"),     
        container="data",
        blob_name="kangwon_notices.csv",
        credential=os.getenv("AZURE_BLOB_CREDENTIAL"),        
    )
