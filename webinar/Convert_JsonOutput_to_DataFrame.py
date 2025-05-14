from breeze_connect import BreezeConnect
import pandas as pd

#Initiliaze SDK
breeze = BreezeConnect(api_key="65yG9N5ie17_7192085Sl92k987h3e58")

#Generate Session
breeze.generate_session(api_secret="tW5J%88C0n^9428+l2M(5%3971849716",session_token="51318682")

#Use get_historical_data_v2 SDK to fetch historical data
response = breeze.get_historical_data_v2(interval="5minute",
    from_date="2023-08-01T09:40:00.000Z",
    to_date="2023-08-08T12:41:00.000Z",
    stock_code="NIFTY",
    exchange_code="NFO",
    product_type="options",
    expiry_date="2023-08-10T07:00:00.000Z",
    right="put",
    strike_price="19550")

if 'Success' in response:
    df = pd.DataFrame(response['Success'])
    print(df)
else:
    print("[ERROR] No 'Success' key in response. Full response:")
    print(response)