import pandas as pd
import io
from fastapi import UploadFile

class FileUtil:
    """
    Utility class for file operations within the TradingApp.
    """
    @staticmethod
    async def to_dataframe(file: UploadFile) -> pd.DataFrame:
        """
        Reads an uploaded file and converts it to a Pandas DataFrame.
        Supports CSV and Excel formats.
        """
        content = await file.read()
        filename = file.filename.lower()
        
        # Reset file pointer for potential future reads if needed
        await file.seek(0)
        
        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content))
        elif filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(content))
        else:
            raise ValueError(f"Unsupported file format: {filename}. Please upload a CSV or Excel file.")
            
        return df
