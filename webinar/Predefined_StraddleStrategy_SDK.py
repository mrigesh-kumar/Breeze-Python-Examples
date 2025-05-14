# Import required libraries
from breeze_strategies import Strategies
from breeze_connect import BreezeConnect
import datetime
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
import calendar

class OptionTrader:
    def __init__(self, app_key: str, secret_key: str, session_key: str):
        self.app_key = app_key
        self.secret_key = secret_key
        self.session_key = session_key
        self.breeze = None
        self.available_funds = 0
        self.min_required_funds = 0

    def connect(self) -> bool:
        """Initialize connection to Breeze API"""
        try:
            self.breeze = BreezeConnect(api_key=self.app_key)
            self.breeze.generate_session(api_secret=self.secret_key, session_token="51318682")
            print("Successfully connected to Breeze API")
            return True
        except Exception as e:
            print(f"Failed to connect to Breeze API: {str(e)}")
            return False

    def get_available_funds(self):
        """Funds check removed as per user request."""
        print("[INFO] Skipping available funds check as per user request.")
        self.available_funds = float('inf')  # Always enough funds
        return {'available_balance': float('inf')}

    def get_active_expiries(self) -> List[str]:
        """Get list of active expiry dates for NIFTY options"""
        try:
            # Get current date
            now = datetime.datetime.now()
            expiries = []
            
            # Add weekly expiries for next 4 weeks
            for i in range(4):
                expiry_date = now + datetime.timedelta(days=(3 - now.weekday() + i*7))  # Thursday
                expiries.append(expiry_date.strftime("%Y-%m-%dT06:00:00.000Z"))
            
            # Add monthly expiry (last Thursday of month)
            last_day = calendar.monthrange(now.year, now.month)[1]
            month_end = datetime.datetime(now.year, now.month, last_day)
            last_thursday = month_end - datetime.timedelta(days=(month_end.weekday() - 3))
            if last_thursday > now:
                expiries.append(last_thursday.strftime("%Y-%m-%dT06:00:00.000Z"))
            
            return expiries
        except Exception as e:
            print(f"Error getting expiry dates: {str(e)}")
            return []

    def check_option_premium(self, strike: str, expiry: str) -> Tuple[float, float]:
        """Get call and put premium for a strike price"""
        try:
            # Get call option quote
            call = self.breeze.get_option_chain_quotes(
                stock_code="NIFTY",
                exchange_code="NFO",
                product_type="options",
                expiry_date=expiry,
                right="call",
                strike_price=strike
            )
            
            # Get put option quote
            put = self.breeze.get_option_chain_quotes(
                stock_code="NIFTY",
                exchange_code="NFO",
                product_type="options",
                expiry_date=expiry,
                right="put",
                strike_price=strike
            )
            
            call_premium = float(call["Success"][0]["ltp"]) if call.get("Success") else 0
            put_premium = float(put["Success"][0]["ltp"]) if put.get("Success") else 0
            
            return call_premium, put_premium
        except Exception as e:
            print(f"Error getting option premiums: {str(e)}")
            return 0, 0

    def find_affordable_strike(self, current_price: float, expiries: List[str], lot_size: int = 75) -> Tuple[str, str, float, Dict[str, float]]:
        """Find an affordable strike price and expiry with margin requirements"""
        try:
            atm_strike = round(current_price / 100) * 100
            strikes_to_check = [atm_strike, atm_strike - 100, atm_strike + 100]
            
            for expiry in expiries:
                print(f"\nChecking expiry: {expiry}")
                for strike in strikes_to_check:
                    call_premium, put_premium = self.check_option_premium(str(strike), expiry)
                    total_cost = (call_premium + put_premium) * lot_size
                    
                    # Calculate estimated margins
                    margin_estimate = {
                        "span_margin": total_cost * 0.15,  # Approximate SPAN margin
                        "exposure_margin": total_cost * 0.05,  # Approximate exposure margin
                        "total_margin": total_cost * 0.20  # Total estimated margin
                    }
                    
                    print(f"\nStrike {strike}:")
                    print(f"Call Premium: ₹{call_premium:,.2f}")
                    print(f"Put Premium: ₹{put_premium:,.2f}")
                    print(f"Total Cost: ₹{total_cost:,.2f}")
                    print(f"Estimated Required Margin: ₹{margin_estimate['total_margin']:,.2f}")
                    
                    # Check if we have enough funds for both premium and margin
                    if (total_cost <= self.available_funds and 
                        margin_estimate['total_margin'] <= self.available_funds):
                        self.min_required_funds = total_cost + margin_estimate['total_margin']
                        return str(strike), expiry, total_cost, margin_estimate
            
            return "", "", 0, {}
        except Exception as e:
            print(f"Error finding affordable strike: {str(e)}")
            return "", "", 0, {}

    def analyze_market_trend(self, analysis_type: str = "intraday") -> str:
        """
        Analyze market trend using technical indicators
        Returns: 'bullish', 'bearish', or 'sideways'
        """
        try:
            # Get historical data for analysis
            end_date = datetime.datetime.now().strftime("%Y-%m-%d")
            if analysis_type == "intraday":
                start_date = (datetime.datetime.now() - datetime.timedelta(days=20)).strftime("%Y-%m-%d")
            else:
                start_date = (datetime.datetime.now() - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
            
            historical_data = self.breeze.get_historical_data(
                interval="1day",
                from_date=start_date,
                to_date=end_date,
                stock_code="NIFTY",
                exchange_code="NSE",
                product_type="cash"
            )
            
            if not historical_data or not historical_data.get("Success"):
                print("Failed to get historical data")
                return None
                
            # Convert to DataFrame
            df = pd.DataFrame(historical_data["Success"])
            
            # Ensure we have numeric values
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Drop any rows with NaN values
            df = df.dropna(subset=['close'])
            
            min_points = 10
            if len(df) < 20:
                print(f"[WARNING] Not enough data points for ideal analysis. Proceeding with {len(df)} days (minimum required: {min_points}).")
                if len(df) < min_points:
                    print(f"[ERROR] Too few data points. Need at least {min_points}, got {len(df)}. Exiting analysis.")
                    return None
            
            if len(df) < 20:
                print(f"[WARNING] Not enough data points for ideal analysis. Proceeding with {len(df)} days (minimum required: {min_points}).")
                if len(df) < min_points:
                    print(f"[ERROR] Too few data points. Need at least {min_points}, got {len(df)}. Exiting analysis.")
                    return None
            
            # Calculate technical indicators
            # 1. Moving Averages
            df['SMA20'] = df['close'].rolling(window=min(20, len(df))).mean()
            df['SMA50'] = df['close'].rolling(window=min(50, len(df))).mean()
            
            # 2. RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=min(14, len(df))).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=min(14, len(df))).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))
            
            # 3. Volatility (20-day)
            df['Volatility'] = df['close'].rolling(window=min(20, len(df))).std()
            
            # Get latest values
            current_price = df['close'].iloc[-1]
            sma20 = df['SMA20'].iloc[-1]
            sma50 = df['SMA50'].iloc[-1]
            rsi = df['RSI'].iloc[-1]
            volatility = df['Volatility'].iloc[-1]
            avg_volatility = df['Volatility'].mean()
            
            # Calculate price change
            price_change = ((current_price - df['close'].iloc[-2]) / df['close'].iloc[-2]) * 100
            
            # Log analysis
            print("\n=== Market Analysis ===")
            print(f"Current Price: {current_price:.2f}")
            print(f"Daily Change: {price_change:.2f}%")
            print(f"20-day SMA: {sma20:.2f}")
            print(f"50-day SMA: {sma50:.2f}")
            print(f"RSI: {rsi:.2f}")
            print(f"Current Volatility: {volatility:.2f}")
            print(f"Average Volatility: {avg_volatility:.2f}")
            
            # Determine market trend
            trend = "sideways"
            reason = []
            
            # Trend based on moving averages
            if current_price > sma20 and sma20 > sma50:
                trend = "bullish"
                reason.append("Price above both SMAs")
            elif current_price < sma20 and sma20 < sma50:
                trend = "bearish"
                reason.append("Price below both SMAs")
                
            # RSI analysis
            if rsi > 70:
                if trend != "bearish":
                    reason.append("RSI indicates overbought")
                    trend = "bearish"
            elif rsi < 30:
                if trend != "bullish":
                    reason.append("RSI indicates oversold")
                    trend = "bullish"
                
            # Volatility analysis
            if volatility > avg_volatility * 1.5:
                reason.append("High volatility detected")
                if abs(price_change) > 1:  # If price change is significant
                    if price_change > 0:
                        trend = "bullish"
                        reason.append("Strong upward momentum")
                    else:
                        trend = "bearish"
                        reason.append("Strong downward momentum")
                else:
                    trend = "sideways"
                    reason.append("No clear direction")
            
            print(f"\nMarket Trend: {trend.upper()}")
            if reason:
                print(f"Reasons: {', '.join(reason)}")
            else:
                print("Reasons: No clear signals, market appears to be range-bound")
            
            return trend
            
        except Exception as e:
            print(f"Error in market analysis: {str(e)}")
            return None

    def suggest_strategy(self, trend: str) -> Dict[str, str]:
        """
        Suggest trading strategy based on market trend
        """
        if trend == "bullish":
            return {
                "strategy_type": "long",
                "stop_loss": "-50",
                "take_profit": "150"
            }
        elif trend == "bearish":
            return {
                "strategy_type": "short",
                "stop_loss": "-50",
                "take_profit": "150"
            }
        else:  # sideways
            return {
                "strategy_type": "long",  # Straddle works well in sideways market
                "stop_loss": "-50",
                "take_profit": "100"
            }

    def get_current_price(self) -> float:
        """Get current market price"""
        try:
            quotes = self.breeze.get_quotes(
                stock_code="NIFTY",
                exchange_code="NSE",
                expiry_date="",
                product_type="cash",
                right="",
                strike_price=""
            )
            if quotes["Success"] and quotes["Success"][0]["ltp"]:
                return float(quotes["Success"][0]["ltp"])
            return 0
        except Exception as e:
            print(f"Error getting current market price: {str(e)}")
            return 0

    def execute_strategy(self, analysis_type: str = "intraday") -> None:
        try:
            # Connect to API
            if not self.connect():
                return

            self.get_available_funds()  # Just sets available_funds to inf and logs info

            # Get market trend
            trend = self.analyze_market_trend(analysis_type)
            if not trend:
                return

            # Get current price
            current_price = self.get_current_price()
            if not current_price:
                return

            # Get active expiries
            expiries = self.get_active_expiries()
            if not expiries:
                print("No valid expiry dates found")
                return

            # Find affordable strike and expiry
            strike, expiry, total_cost, margin_estimate = self.find_affordable_strike(current_price, expiries)
            if not strike:
                print(f"\nNo affordable strikes found. Minimum required: ₹{self.min_required_funds:,.2f}")
                print(f"Available funds: ₹{self.available_funds:,.2f}")
                return

            print(f"\nSelected Strategy:")
            print(f"Strike Price: {strike}")
            print(f"Expiry Date: {expiry}")
            print(f"Total Cost: ₹{total_cost:,.2f}")
            print(f"Estimated Margin: ₹{margin_estimate['total_margin']:,.2f}")
            print(f"Available Funds: ₹{self.available_funds:,.2f}")

            # Get strategy parameters based on trend
            strategy_params = self.suggest_strategy(trend)
            
            # Execute the strategy
            try:
                print("\nInitializing strategy...")
                obj = Strategies(
                    app_key=self.app_key,
                    secret_key=self.secret_key,
                    api_session=self.session_key,
                    max_profit=strategy_params["take_profit"],
                    max_loss=strategy_params["stop_loss"]
                )
                print("Strategy object created successfully")

                print(f"\nExecuting {strategy_params['strategy_type']} straddle strategy...")
                obj.straddle(
                    strategy_type=strategy_params["strategy_type"],
                    stock_code="NIFTY",
                    strike_price=strike,
                    quantity="75",
                    expiry_date=expiry
                )
            except Exception as e:
                print(f"Error executing strategy: {str(e)}")

            # Square off positions
            try:
                print("\nSquaring off positions...")
                obj.stop()
            except Exception as e:
                print(f"Error squaring off positions: {str(e)}")

        except Exception as e:
            print(f"Error in strategy execution: {str(e)}")

def main():
    # Configure API credentials
    app_key = "65yG9N5ie17_7192085Sl92k987h3e58"
    secret_key = "tW5J%88C0n^9428+l2M(5%3971849716"
    session_key = "51316056"

    trader = OptionTrader(app_key, secret_key, session_key)

    while True:
        print("\nChoose Analysis Type:")
        print("1. Intraday Trading")
        print("2. Monthly Expiry Trading")
        print("3. Exit")
        
        choice = input("\nEnter your choice (1-3): ")
        
        if choice == "1":
            trader.execute_strategy("intraday")
        elif choice == "2":
            trader.execute_strategy("monthly")
        elif choice == "3":
            print("Exiting...")
            break
        else:
            print("Invalid choice. Please try again.")

if __name__ == "__main__":
    main()
