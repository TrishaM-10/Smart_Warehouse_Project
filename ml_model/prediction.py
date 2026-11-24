import pandas as pd
import numpy as np

from sklearn.ensemble import RandomForestRegressor

from database.db_connection import get_db_connection


# =========================================
# 1. FETCH HISTORICAL SALES DATA
# =========================================

def get_sales_data(product_id):

    db = get_db_connection()

    if db is None:
        print("Database connection failed!")
        return pd.DataFrame()

    cursor = None

    try:
        cursor = db.cursor(dictionary=True)

        query = """
            SELECT
                DATE(sale_date) AS sale_date,
                SUM(quantity_sold) AS daily_sales
            FROM sales
            WHERE product_id = %s
            GROUP BY DATE(sale_date)
            ORDER BY DATE(sale_date)
        """

        cursor.execute(query, (product_id,))

        records = cursor.fetchall()

        df = pd.DataFrame(records)

        if df.empty:
            print(f"No sales records found for product ID: {product_id}")
            return df

        df['sale_date'] = pd.to_datetime(df['sale_date'])

        df['daily_sales'] = pd.to_numeric(
            df['daily_sales'],
            errors='coerce'
        ).astype(float)

        print(f"Successfully fetched {len(df)} sales records for product {product_id}")

        return df

    except Exception as error:

        print("Sales Data Error:", repr(error))

        return pd.DataFrame()

    finally:

        if cursor is not None:
            cursor.close()

        db.close()


# =========================================
# 2. PREPARE DATA FOR MACHINE LEARNING
# =========================================

def prepare_data(df):

    df = df.copy()

    df['sale_date'] = pd.to_datetime(df['sale_date'])

    df['daily_sales'] = pd.to_numeric(
        df['daily_sales'],
        errors='coerce'
    ).astype(float)

    df = df.sort_values('sale_date')

    df = df.set_index('sale_date')

    full_dates = pd.date_range(
        start=df.index.min(),
        end=df.index.max(),
        freq='D'
    )

    df = df.reindex(full_dates)

    df.index.name = 'sale_date'

    df['daily_sales'] = df['daily_sales'].fillna(0.0)

    df = df.reset_index()

    # Date features
    df['day'] = df['sale_date'].dt.day
    df['month'] = df['sale_date'].dt.month
    df['day_of_week'] = df['sale_date'].dt.dayofweek

    # Historical sales features
    df['lag_1'] = df['daily_sales'].shift(1)

    df['lag_7'] = df['daily_sales'].shift(7)

    df['rolling_7'] = (
        df['daily_sales']
        .shift(1)
        .rolling(window=7)
        .mean()
    )

    df = df.dropna().reset_index(drop=True)

    return df


# =========================================
# 3. FORECAST PRODUCT DEMAND
# =========================================

def forecast_product(product_id):

    df = get_sales_data(product_id)

    if df.empty:
        return {
            'error': 'No sales history available for this product.'
        }

    if len(df) < 10:
        return {
            'error': 'Not enough sales history to generate predictions.'
        }

    prepared_df = prepare_data(df)

    if len(prepared_df) < 3:
        return {
            'error': 'Not enough training data to generate predictions.'
        }

    features = [
        'day',
        'month',
        'day_of_week',
        'lag_1',
        'lag_7',
        'rolling_7'
    ]

    X = prepared_df[features].astype(float)

    y = prepared_df['daily_sales'].astype(float)

    # =====================================
    # 4. TRAIN RANDOM FOREST MODEL
    # =====================================

    model = RandomForestRegressor(
        n_estimators=100,
        random_state=42,
        max_depth=8
    )

    model.fit(X, y)

    # =====================================
    # 5. GENERATE 7-DAY FORECAST
    # =====================================

    last_sales = df['daily_sales'].astype(float).tolist()

    last_date = df['sale_date'].max()

    forecast = []

    for i in range(1, 8):

        next_date = last_date + pd.Timedelta(days=i)

        lag_1 = float(last_sales[-1])

        lag_7 = float(last_sales[-7])

        rolling_7 = float(np.mean(last_sales[-7:]))

        input_data = pd.DataFrame([{
            'day': next_date.day,
            'month': next_date.month,
            'day_of_week': next_date.dayofweek,
            'lag_1': lag_1,
            'lag_7': lag_7,
            'rolling_7': rolling_7
        }])

        predicted_demand = float(
            model.predict(input_data[features])[0]
        )

        predicted_demand = max(0.0, predicted_demand)

        forecast.append({
            'date': next_date.strftime('%d-%m-%Y'),
            'predicted_demand': round(predicted_demand, 2)
        })

        last_sales.append(predicted_demand)

    # =====================================
    # 6. CALCULATE DEMAND TREND
    # =====================================

    previous_average = float(
        np.mean(df['daily_sales'].tail(7))
    )

    average_demand = float(
        np.mean([
            item['predicted_demand']
            for item in forecast
        ])
    )

    if average_demand > previous_average * 1.05:
        trend = 'Increasing'

    elif average_demand < previous_average * 0.95:
        trend = 'Decreasing'

    else:
        trend = 'Stable'

    # =====================================
    # 7. RETURN RESULTS
    # =====================================

    return {
        'forecast': forecast,
        'average_demand': round(average_demand, 2),
        'previous_average': round(previous_average, 2),
        'trend': trend
    }