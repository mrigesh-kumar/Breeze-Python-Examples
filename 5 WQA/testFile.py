import configparser
from breeze_connect import BreezeConnect
from datetime import datetime
import traceback
import os



# Load config
config = configparser.RawConfigParser()
config_path = os.path.join(os.path.dirname(__file__), 'config.properties')
config.read(config_path)

api_key = config['DEFAULT'].get('app_key')
api_secret = config['DEFAULT'].get('secret_key')
session_token = config['DEFAULT'].get('session_token')

# Minimal test for cash segment (RELIANCE, NSE)
def minimal_breeze_historical_test():
    print("[INFO] Starting minimal BreezeConnect historical data test...")
    print("session_token : " , session_token , "api_secret : " , api_secret)

    try:
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret, session_token=session_token)
        params = {
            'interval': '1minute',
            'from_date': '2024-04-01T09:30:00.000Z',
            'to_date': '2024-04-02T09:30:00.000Z',
            'stock_code': 'RELIANCE',
            'exchange_code': 'NSE',
            'product_type': 'cash'
        }
        print("[DEBUG] Using parameters:")
        for k, v in params.items():
            print(f"  {k}: {v}")
        response = breeze.get_historical_data(**params)
        print("[DEBUG] Breeze API response:")
        print(response)
        return response
    except Exception as e:
        print(f"[ERROR] Exception during Breeze API test: {e}")
        print("[ERROR] Full stack trace:")
        traceback.print_exc()
        return None

if __name__ == "__main__":
    minimal_breeze_historical_test()