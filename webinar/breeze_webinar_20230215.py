from breeze_connect import BreezeConnect
from datetime import datetime
import pandas as pd

breeze = BreezeConnect(api_key="65yG9N5ie17_7192085Sl92k987h3e58")
breeze.generate_session(api_secret="tW5J%88C0n^9428+l2M(5%3971849716", session_token="51484973")

symbol = "LIC"
time_interval = "5minute"
start_date = datetime(2025, 5, 14, 9, 15,0)
end_date = datetime(2025, 5, 14, 15, 15,0)
exchange = "NSE"
expiry = datetime(2025, 5, 29, 0,0,0)

#!Note how get_names() is used to convert any symbology to any other symbology
breeze.get_names(exchange_code="NSE", stock_code=symbol)
'''
{
    'exchange_code': 'NSE', 
    'exchange_stock_code': 'NIFTY BANK', 
    'isec_stock_code': 'CNXBAN', 
    'isec_token': 'NIFTY BANK', 
    'company name': 'NIFTY BANK', 
    'isec_token_level1': '4.1!NIFTY BANK', 
    'isec_token_level2': '4.2!NIFTY BANK'
    }
'''

#! Use get_names to fetch 1second data
print(start_date)
data2 = breeze.get_historical_data_v2(interval = time_interval,
                            from_date = start_date,
                            to_date   = end_date,
                            stock_code = breeze.get_names(exchange_code="NSE", stock_code=symbol)['isec_stock_code'],
                            product_type="futures",
                            expiry_date=expiry,
                            exchange_code = exchange)

df2 = pd.DataFrame(data2['Success'])
print(df2)

#!One Click F&O Sockets
# Connect to Breeze socket
breeze.ws_connect()
# Define data handling function - whenever a tick comes in, this is what will be done with it
def on_event_data(ticks):
    print("Time: ", datetime.now().isoformat() , " Ticks: {}".format(ticks))
# Assign above function to Breeze socket listener
breeze.on_ticks = on_event_data


#!Preview Order
breeze.preview_order(
    stock_code = "ICIBAN",
    exchange_code = "NSE",
    product = "margin",
    order_type = "limit",
    price = "907.05",
    action = "buy",
    quantity = "1",
    specialflag = "N"
)

'''
{
    'Success': {
        'brokerage': 6.8029, 
        'exchange_turnover_charges': 0.0254, 
        'stamp_duty': 0.1361, 
        'stt': 0.9071, 
        'sebi_charges': 0.0009, 
        'gst': 1.2293, 
        'total_turnover_and_sebi_charges': 0.0263, 
        'total_other_charges': 2.2987, 
        'total_brokerage': 9.1015
        },
    'Status': 200, 
    'Error': None
}
'''
