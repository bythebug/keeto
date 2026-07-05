# Google Gemini

Keeto captures Google Gemini API calls via the `google-generativeai` SDK.

## Setup

```python
from keeto import monitor
monitor.start()

import google.generativeai as genai
genai.configure(api_key="YOUR_API_KEY")
```

## What's captured

- Model name
- Input/output token counts
- Cost (from Keeto pricing table)
- Latency
- Safety ratings

## Basic usage

```python
model = genai.GenerativeModel("gemini-1.5-flash")
response = model.generate_content("Explain quantum computing.")
print(response.text)
```

## Streaming

```python
response = model.generate_content("Write a poem.", stream=True)
for chunk in response:
    print(chunk.text, end="")
```

## Chat

```python
chat = model.start_chat()
response = chat.send_message("What is 2+2?")
response = chat.send_message("Multiply that by 10.")
# Each turn captured as a separate span in the same trace
```

## Pricing

Gemini pricing entries are included in Keeto's pricing table. Token costs are automatically computed.
