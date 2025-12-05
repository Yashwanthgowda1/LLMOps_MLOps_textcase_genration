from fastapi import Body
import requests

@app.post("/full-analysis")
def full_analysis(input_data: dict = Body(...)):
    topic = input_data.get("topic")

    if not topic:
        return {"error": "topic field is required"}

    # 1️⃣ CALL MARKET API
    market_payload = {"input": {"topic": topic}}
    market_res = requests.post("http://localhost:8000/market/invoke", json=market_payload)
    market_output = market_res.json()["result"]["output_text"]

    # 2️⃣ CALL SUMMARY API
    summary_payload = {"input": {"topic": market_output}}
    summary_res = requests.post("http://localhost:8000/summary/invoke", json=summary_payload)
    summary_output = summary_res.json()["result"]["output_text"]

    # 3️⃣ CALL FINAL DECISION MAKER
    final_payload = {
        "input": {
            "take_actual_summary": summary_output,
            "main_output": market_output
        }
    }
    final_res = requests.post("http://localhost:8000/openai/invoke", json=final_payload)
    final_output = final_res.json()["result"]["output_text"]

    # 4️⃣ RETURN ALL RESULTS
    return {
        "market_research": market_output,
        "summary": summary_output,
        "final_decision": final_output
    }
