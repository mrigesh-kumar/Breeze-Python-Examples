# Make sure to install latest library of Breeze before trying the below code. 
# shell command => pip install --upgrade breeze-connect 


#intialize keys
api_key = "65yG9N5ie17_7192085Sl92k987h3e58"
api_secret = "tW5J%88C0n^9428+l2M(5%3971849716"
api_session = '51316243'

#import libraries
from breeze_connect import BreezeConnect

# Initialize SDK
api = BreezeConnect(api_key=api_key)

# Generate Session
api.generate_session(api_secret=api_secret,
                      session_token=api_session)


# Fetch Data using historical data API v2
data = api.get_historical_data_v2(interval="5minute",
                            from_date= "2022-08-15T07:00:00.000Z",
                            to_date= "2022-08-17T07:00:00.000Z",
                            stock_code="ITC",
                            exchange_code="NSE",
                            product_type="cash")


# Convert data (API JSON response) into a table / dataframe using pandas library
import pandas as pd
df = pd.DataFrame(data['Success'])

print(df)
