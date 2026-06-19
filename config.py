# PSX Tracker — Global Configuration
import os

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATABASE     = os.path.join(BASE_DIR, 'data.db')
SYMBOLS_CACHE = os.path.join(BASE_DIR, 'psx_symbols_backup.json')

INDIVIDUALS  = ['kashif', 'shahvez']
TAX_RATE     = 0.15        # 15% capital gains tax
PRICE_REFRESH_SECONDS = 30 # How often frontend polls for live prices
PSX_SYMBOLS_URL = "https://www.psx.com.pk/market-data/equities"
