"""Вымышленный каталог телевизоров с остатками по магазинам. Только для демонстрации."""
import pandas as pd

from .config import CATALOG_PATH


def load_catalog(path=CATALOG_PATH) -> pd.DataFrame:
    df = pd.read_csv(path)
    int_cols = ["diagonal_in", "refresh_hz", "hdmi21", "brightness_nits", "price",
                "stock_store1", "stock_store2", "stock_store3", "stock_warehouse"]
    df[int_cols] = df[int_cols].astype(int)
    if "width_cm" not in df.columns:
        # В демо-каталоге ширины нет: считаем по диагонали 16:9 (+3 см на рамку). На витринах берём из карточки.
        df["width_cm"] = (df["diagonal_in"] * 2.54 * 0.8716 + 3).round().astype(int)
        df.attrs["width_estimated"] = True
    return df
