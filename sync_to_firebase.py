import psycopg2
import requests
import json
from datetime import datetime
from decimal import Decimal

FIREBASE_URL = "https://dbmsproject-2191b-default-rtdb.firebaseio.com/"  

db_config = {
    "dbname": "studysync_db",
    "user": "postgres",
    "password": "pgadmin4",
    "host": "localhost",
    "port": "5432"
}

tables = ['user','course','enrollment','assignment','submission','deleted_enrollments','progress']

def fetch_table_data(cursor, table):
    cursor.execute(f'SELECT * FROM "{table}"')
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    result = []

    for row in rows:
        row_dict = {}
        for col, val in zip(columns, row):
            if isinstance(val, datetime):
                row_dict[col] = val.isoformat()
            elif isinstance(val, Decimal):
                row_dict[col] = float(val)  
            else:
                row_dict[col] = val
        result.append(row_dict)
    return result

def push_to_firebase(data, table_name):
    url = f"{FIREBASE_URL}/{table_name}.json"
    response = requests.put(url, data=json.dumps(data))
    if response.status_code == 200:
        print(f" Synced table '{table_name}' to Firebase.")
    else:
        print(f" Failed to sync '{table_name}': {response.status_code} - {response.text}")

def main():
    try:
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        for table in tables:
            print(f" Syncing '{table}'...")
            data = fetch_table_data(cursor, table)
            push_to_firebase(data, table)
        cursor.close()
        conn.close()
    except Exception as e:
        print(f" Error: {e}")

if __name__ == "__main__":
    main()
