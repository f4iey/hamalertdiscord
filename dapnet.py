# Functions for DAPNET API integration
import requests

def send(user, password, data, dest_call):
    url = 'http://www.hampager.de:8080/calls'
    headers = {'Content-type': 'application/json'}
    payload = "{" + f' "text": "{user.upper()}: {data}", "callSignNames": ["{dest_call.lower()}"], "transmitterGroupNames": ["all"], "emergency": false' + " }"
    payload = payload.encode('utf-8')
    response = requests.post(url, headers=headers, auth=(user, password), data=payload)
    print(response)

def get(user, password):
    url = 'http://www.hampager.de:8080/calls'
    headers = {'Content-type': 'application/json'}
    response = requests.get(url, headers=headers, params={"ownerName": f"{user.lower()}"}, auth=(user, password))
    strout = response.json()
    return strout["text"]