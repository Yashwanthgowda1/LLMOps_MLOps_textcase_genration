import requests



json={
    'input':{"topic": "write stock of Infosys"}
}
responce=requests.post("http://localhost:8000/market/invoke",
              json=json)
main_output=(responce.json()['output']['content'])

json={
    "input":{"topic":main_output

    }
}
responce_summery=requests.post("http://localhost:8000/summary/invoke",
              json=json)
take_actual_summery=(responce_summery.json()['output']['content'])

# final decision maker
json={
    "input":{
        "take_actual_summary":take_actual_summery,
        "main_output": main_output

    }
}

responce=requests.post("http://localhost:8000/openai/invoke",
            json=json)
print(responce.json())

