from fastapi import FastAPI
import requests
from pydantic import BaseModel,Field
topics=input("enter the stock")
market_payload = {"input": {"topic": topics}}
market_res = requests.post("http://localhost:8000/market/invoke", json=market_payload)
market_output = market_res.json()["output"]["content"]

print("Market Output:", market_output)  # <--- PRINT HERE

    # 2️⃣ SUMMARY API
summary_payload = {"input": {"topic": market_output}}
summary_res = requests.post("http://localhost:8000/summary/invoke", json=summary_payload)
summary_output = summary_res.json()["output"]["content"]

print("Summary Output:", summary_output)  # <--- PRINT HERE

    # 3️⃣ FINAL DECISION MAKER
final_payload = {
        "input": {
            "take_actual_summary": summary_output,
            "main_output": market_output
        }
    }
final_res = requests.post("http://localhost:8000/openai/invoke", json=final_payload)
final_output = final_res.json()["output"]["content"]

print("Final Output:", final_output)  # <--- PRINT HERE
