#intialize keys

api_key = "65yG9N5ie17_7192085Sl92k987h3e58"
api_secret = "tW5J%88C0n^9428+l2M(5%3971849716"
session_token = "51318682"

# *********************************************************************************************************************************************************************



# Import Libraries

from datetime import datetime
import pandas as pd
from breeze_connect import BreezeConnect

# Setup my API keys 
api = BreezeConnect(api_key=api_key)
api.generate_session(api_secret=api_secret,session_token=session_token)


# *********************************************************************************************************************************************************************

# Callback to receive ticks.
# Event based function

def on_ticks(ticks):
    print(ticks)
        
# *********************************************************************************************************************************************************************
    
  
# Main Function        
if __name__ == "__main__":
    print ("Starting Execution \n")

    #Switch on Websockets
    api.ws_connect()
    api.on_ticks = on_ticks
    
    api.subscribe_feeds(exchange_code="NFO", 
                    stock_code='NIFTY', 
                    product_type="options", 
                    expiry_date='27-Apr-2023', 
                    strike_price='17500', 
                    right='call', interval="1minute")
