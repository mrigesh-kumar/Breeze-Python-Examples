import sys
import bisect
import datetime
import mibian   #to easily calculate iv and greeks  (not the fastest way though)
import configparser
import os
from breeze_connect import BreezeConnect

flt_rf = 0.058
int_days_to_expiry = (datetime.datetime(2025,5,29, 0, 0, 0) - datetime.datetime.today()).days

# Read config
config = configparser.RawConfigParser()
config_path = os.path.join(os.path.dirname(__file__), 'config.properties')
config.read(config_path)

api_key = config['DEFAULT']['app_key']
api_secret = config['DEFAULT']['secret_key']
session_token = config['DEFAULT']['session_token']

def n_highest(int_strikes_away, flt_spot, list_strikes):
    '''
    REQUIRES: 
        import bisect (https://docs.python.org/3/library/bisect.html)
    
    INPUTS:
        int_strikes_away = how many strikes away do you want to find? negative will look ITM, positive OTM
        flt_spot = the spot price wrt which we're looking for a spot
        list_strikes = list of all available strikes

    OUTPUT:
        flt_next_highest_strike = returns the strike needed to be used
    '''
    a = sorted(list_strikes)
    flt_next_highest_strike = a[bisect.bisect_left(a, flt_spot) + int_strikes_away - 1]
    return flt_next_highest_strike

app = BreezeConnect(api_key=api_key)
app.generate_session(api_secret=api_secret, session_token=session_token)

# Fetch option chain data with error handling
call_response = app.get_option_chain_quotes(
    stock_code='CNXBAN',
    exchange_code='NFO',
    right='call',
    expiry_date=datetime.date(2023,4,27).strftime(r'%d-%b-%Y'),
    product_type='options'
)
put_response = app.get_option_chain_quotes(
    stock_code='CNXBAN',
    exchange_code='NFO',
    right='put',
    expiry_date=datetime.date(2023,4,27).strftime(r'%d-%b-%Y'),
    product_type='options'
)

list_call_chain = call_response.get('Success')
list_put_chain = put_response.get('Success')

if not list_call_chain or not isinstance(list_call_chain, list):
    print('[ERROR] No call option chain data returned:', call_response)
    list_call_chain = []
if not list_put_chain or not isinstance(list_put_chain, list):
    print('[ERROR] No put option chain data returned:', put_response)
    list_put_chain = []

if 'Error' in call_response:
    print('[API ERROR - CALL]:', call_response['Error'])
if 'Error' in put_response:
    print('[API ERROR - PUT]:', put_response['Error'])

if not list_call_chain or not list_put_chain:
    print('[FATAL] No option chain data available. Exiting.')
    sys.exit(1)

list_call_chain = [item for item in list_call_chain if item['ltt']!='']
list_put_chain = [item for item in list_put_chain if item['ltt']!='']

list_call_strikes = [item['strike_price'] for item in list_call_chain]
list_put_strikes = [item['strike_price'] for item in list_put_chain]

list_diff = list(set(list_call_strikes).symmetric_difference(set(list_put_strikes)))

list_call_chain = [item for item in list_call_chain if item['strike_price'] not in list_diff]
list_put_chain = [item for item in list_put_chain if item['strike_price'] not in list_diff]
len(list_call_chain)
len(list_put_chain)

list_call_strikes = [item['strike_price'] for item in list_call_chain]
list_put_strikes = [item['strike_price'] for item in list_put_chain]


dict_fut_quote = app.get_quotes(
    stock_code='CNXBAN',
    exchange_code='NFO',
    product_type='futures',
    expiry_date=datetime.date(2025,5,15).strftime(r'%d-%b-%Y')
    )['Success'][0]

#!STRIKE SELECTION BY ABSOLUTE COUNT AWAY FROM ATM
#?: "ATM" is defined as per NSE definition in VIX documentation: "the strike price immediately lower than the spot".
n_highest(int_strikes_away=-5,
          flt_spot=dict_fut_quote['ltp'],
          list_strikes=list_call_strikes)


#!STRIKE SELECTION BASED ON DELTA
#? assume we want a call with Delta
for item in list_call_chain:
    iv = mibian.BS([dict_fut_quote['ltp'], item['strike_price'], flt_rf, int_days_to_expiry], callPrice=item['ltp']).impliedVolatility
    delta = mibian.BS([dict_fut_quote['ltp'], item['strike_price'], flt_rf, int_days_to_expiry],volatility=iv).callDelta
    item['iv'] = iv
    item['delta'] = delta
for item in list_put_chain:
    iv = mibian.BS([dict_fut_quote['ltp'], item['strike_price'], flt_rf, int_days_to_expiry], putPrice=item['ltp']).impliedVolatility
    delta = mibian.BS([dict_fut_quote['ltp'], item['strike_price'], flt_rf, int_days_to_expiry],volatility=iv).putDelta
    item['iv'] = iv
    item['delta'] = delta

list_call_delta = [item['delta'] for item in list_call_chain]
list_put_delta = [item['delta'] for item in list_put_chain]

list_sum_delta = [cd + pd for cd, pd in zip(list_call_delta, list_put_delta)]

list_sum_delta[bisect.bisect(list_sum_delta, 0)]
ind_zero_delta = list_sum_delta.index(0.061036296556833514)
list_call_chain[ind_zero_delta]
list_put_chain[ind_zero_delta]

#!STRIKE SELECTION BASED ON PREMIUM WE WANT TO PAY
#? let's assume that we want to pay less than 100 as premium for any OTM call


# https://api.icicidirect.com/apiuser/home